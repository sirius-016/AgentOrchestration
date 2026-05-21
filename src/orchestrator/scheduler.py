"""Task Scheduler - Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
import logging
from typing import Any, Dict, Optional, Set
from uuid import uuid4
from enum import Enum

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """Task lifecycle states for reconcile validation."""
    PENDING = "pending"
    DISPATCHED = "dispatched"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReconcileError(Exception):
    """Raised when queue and state diverge during dispatch."""
    pass


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._task_states: Dict[str, TaskState] = {}  # NEW: track task states
        self._task_revisions: Dict[str, int] = {}  # NEW: track task revisions for optimistic locking
        self._max_retries = 3
        self._reconcile_attempts: Dict[str, int] = {}  # NEW: track reconcile attempts

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["revision"] = 0  # NEW: initial revision

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        
        # NEW: Initialize task state
        self._task_states[task_id] = TaskState.PENDING
        self._task_revisions[task_id] = 0
        
        logger.debug(f"Enqueued task {task_id} with state PENDING")
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["revision"] = 0
        self._scheduled[task_id] = time.time() + delay
        self._task_states[task_id] = TaskState.PENDING
        self._task_revisions[task_id] = 0
        return task_id

    def _reconcile_check(self, task_id: str, expected_state: TaskState, expected_revision: int) -> bool:
        """Validate task state before dispatch to prevent queue/state divergence.
        
        This is the core guard for Issue #81 - ensures that:
        1. Task exists and has expected state
        2. Revision matches (optimistic locking)
        3. Task is not stale, duplicate, or policy-violating
        """
        current_state = self._task_states.get(task_id)
        current_revision = self._task_revisions.get(task_id, -1)
        
        if current_state is None:
            logger.warning(f"Reconcile failed: task {task_id} not found in state tracking")
            return False
        
        if current_state != expected_state:
            logger.warning(f"Reconcile failed: task {task_id} state mismatch. Expected {expected_state}, got {current_state}")
            return False
        
        if current_revision != expected_revision:
            logger.warning(f"Reconcile failed: task {task_id} revision mismatch. Expected {expected_revision}, got {current_revision}")
            return False
        
        # Check for policy violations
        if current_state in (TaskState.COMPLETED, TaskState.CANCELLED):
            logger.warning(f"Reconcile failed: task {task_id} is in terminal state {current_state}")
            return False
        
        return True

    def _transition_state(self, task_id: str, new_state: TaskState) -> bool:
        """Atomically transition task state with revision increment."""
        if task_id not in self._task_states:
            return False
        
        old_state = self._task_states[task_id]
        
        # Validate state transition order
        valid_transitions = {
            TaskState.PENDING: {TaskState.DISPATCHED, TaskState.CANCELLED},
            TaskState.DISPATCHED: {TaskState.IN_FLIGHT, TaskState.FAILED, TaskState.CANCELLED},
            TaskState.IN_FLIGHT: {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED},
            TaskState.FAILED: {TaskState.PENDING},  # Allow retry
            TaskState.COMPLETED: set(),  # Terminal
            TaskState.CANCELLED: set(),  # Terminal
        }
        
        if new_state not in valid_transitions.get(old_state, set()):
            logger.warning(f"Invalid state transition: {old_state} -> {new_state} for task {task_id}")
            return False
        
        self._task_states[task_id] = new_state
        self._task_revisions[task_id] = self._task_revisions.get(task_id, 0) + 1
        logger.debug(f"Task {task_id} transitioned: {old_state} -> {new_state} (rev {self._task_revisions[task_id]})")
        return True

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        """Dequeue a task with reconcile validation.
        
        Raises ReconcileError if queue and state diverge during partial dispatch failures.
        """
        now = time.time()
        
        # Move scheduled tasks that are due
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            task_id = task["id"]
            
            # NEW: Reconcile check before dispatch
            expected_revision = task.get("revision", 0)
            
            if not self._reconcile_check(task_id, TaskState.PENDING, expected_revision):
                # Queue and state have diverged - log and attempt recovery
                logger.error(f"Reconcile failed for task {task_id}. Queue/state divergence detected.")
                
                # Track reconcile attempts
                self._reconcile_attempts[task_id] = self._reconcile_attempts.get(task_id, 0) + 1
                
                if self._reconcile_attempts[task_id] > self._max_retries:
                    # Give up and mark as failed
                    self._task_states[task_id] = TaskState.FAILED
                    logger.error(f"Task {task_id} marked FAILED after {self._max_retries} reconcile failures")
                    raise ReconcileError(f"Queue/state divergence for task {task_id} after max retries")
                
                # Re-queue for retry
                task["retries"] = task.get("retries", 0) + 1
                self._queues[queue].push(task, 0)  # Lower priority for reconcile retry
                return None
            
            # State is valid - proceed with dispatch
            self._transition_state(task_id, TaskState.DISPATCHED)
            task["revision"] = self._task_revisions[task_id]
            
            self._in_flight[task_id] = task
            task["dequeued_at"] = now
            
            logger.info(f"Dispatched task {task_id} with revision {task['revision']}")
            return task

        await asyncio.sleep(timeout)
        return None

    def ack(self, task_id: str) -> bool:
        """Acknowledge successful task completion."""
        if task_id in self._in_flight:
            task = self._in_flight.pop(task_id)
            success = self._transition_state(task_id, TaskState.COMPLETED)
            if success:
                logger.info(f"Task {task_id} completed successfully")
            return success
        return False

    def nack(self, task_id: str, reason: str = "") -> bool:
        """Negatively acknowledge task failure."""
        if task_id in self._in_flight:
            task = self._in_flight.pop(task_id)
            task["error"] = reason
            task["retries"] = task.get("retries", 0) + 1
            
            if task["retries"] < self._max_retries:
                # Re-queue for retry
                success = self._transition_state(task_id, TaskState.PENDING)
                if success:
                    self._queues["default"].push(task, 0)
                    logger.info(f"Task {task_id} re-queued for retry {task['retries']}/{self._max_retries}")
                return success
            else:
                # Max retries exceeded
                success = self._transition_state(task_id, TaskState.FAILED)
                logger.error(f"Task {task_id} failed permanently: {reason}")
                return success
        return False

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending or in-flight task."""
        if task_id in self._in_flight:
            self._in_flight.pop(task_id)
            return self._transition_state(task_id, TaskState.CANCELLED)
        
        if task_id in self._task_states:
            return self._transition_state(task_id, TaskState.CANCELLED)
        
        return False

    def get_state(self, task_id: str) -> Optional[TaskState]:
        """Get current task state for monitoring."""
        return self._task_states.get(task_id)

    def get_revision(self, task_id: str) -> int:
        """Get current task revision for optimistic locking."""
        return self._task_revisions.get(task_id, -1)
