"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
import uuid
from typing import Any, Dict, Optional
from uuid import uuid4


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
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
        deterministic_key: Optional[str] = None,
    ) -> str:
        """Enqueue a task with optional deterministic key for idempotent checkpointing.
        
        Args:
            task: Task dictionary
            queue: Queue name
            priority: Priority (higher = processed first)
            deterministic_key: If provided, use this as task ID for idempotent writes.
                             Format: "task_id:step_id:attempt_id"
        
        Returns:
            Task ID (either deterministic or generated)
        """
        if deterministic_key and ':' in deterministic_key:
            # Use deterministic key for idempotent checkpoint writes
            parts = deterministic_key.split(':')
            task_id = parts[0]
            step_id = parts[1] if len(parts) > 1 else "default"
            attempt_id = parts[2] if len(parts) > 2 else "1"
        else:
            task_id = str(uuid4())
            step_id = task.get("step_id", "default")
            attempt_id = task.get("attempt_id", "1")
        
        task["id"] = task_id
        task["step_id"] = step_id
        task["attempt_id"] = attempt_id
        task["enqueued_at"] = time.time()
        task["retries"] = task.get("retries", 0)

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["step_id"] = task.get("step_id", "default")
        task["attempt_id"] = task.get("attempt_id", "1")
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        """Mark task as failed and retry if under max retries.
        
        Uses deterministic key (task_id:step_id:attempt_id) for checkpoint idempotency.
        On retry, increments attempt_id to create new checkpoint key.
        
        Returns:
            True if task was requeued, False if max retries exceeded
        """
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                # Increment attempt_id for retry (creates new checkpoint key)
                current_attempt = int(task.get("attempt_id", "1"))
                task["attempt_id"] = str(current_attempt + 1)
                task.pop("checkpoint_data", None)  # Don't propagate old checkpoint
                
                self.enqueue(task, queue, priority=task.get("priority", 0))
                logger = __import__("logging").getLogger(__name__)
                logger.info(f"Retrying task {task_id} (attempt {task['attempt_id']})")
                return True
        return False
