"""Task Scheduler -- Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


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


class CapacityLimiter:
    """Tracks and enforces queue capacity limits.

    When an enqueue operation rolls back (e.g., due to a transaction failure),
    the reserved capacity must be released to prevent capacity leaks that can
    starve subsequent enqueue operations.
    """

    def __init__(self, max_capacity: int = 1000):
        self._max_capacity = max_capacity
        self._used_capacity = 0
        self._reserved: Dict[str, int] = {}  # task_id -> reserved amount

    def reserve(self, task_id: str, amount: int = 1) -> bool:
        """Reserve capacity for a task. Returns False if insufficient capacity."""
        if self._used_capacity + amount > self._max_capacity:
            return False
        self._used_capacity += amount
        self._reserved[task_id] = amount
        logger.debug(f"Reserved capacity for {task_id}: {amount} (used: {self._used_capacity}/{self._max_capacity})")
        return True

    def commit(self, task_id: str) -> bool:
        """Commit a previously reserved capacity. The reservation becomes permanent."""
        if task_id in self._reserved:
            del self._reserved[task_id]
            return True
        return False

    def release(self, task_id: str) -> bool:
        """Release reserved capacity when an enqueue rolls back.

        This is the critical fix: when a transaction fails after capacity was
        reserved, we must release it back to prevent capacity leaks.
        """
        amount = self._reserved.pop(task_id, None)
        if amount is not None:
            self._used_capacity -= amount
            logger.info(f"Released capacity for {task_id}: {amount} (used: {self._used_capacity}/{self._max_capacity})")
            return True
        return False

    @property
    def available(self) -> int:
        return self._max_capacity - self._used_capacity

    @property
    def used(self) -> int:
        return self._used_capacity


class TaskScheduler:
    def __init__(self, max_capacity: int = 1000):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._capacity = CapacityLimiter(max_capacity)
        self._max_retries = 3

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        # Reserve capacity before queueing
        if not self._capacity.reserve(task_id):
            logger.warning(f"Capacity exhausted, cannot enqueue task {task_id}")
            raise ResourceExhaustedError(f"Queue capacity exhausted ({self._capacity.used}/{self._capacity._max_capacity})")

        try:
            if queue not in self._queues:
                self._queues[queue] = PriorityQueue()
            self._queues[queue].push(task, priority)
            # Commit the reservation on successful enqueue
            self._capacity.commit(task_id)
        except Exception as e:
            # Release capacity on enqueue failure (rollback)
            self._capacity.release(task_id)
            logger.error(f"Enqueue failed for task {task_id}, released capacity: {e}")
            raise

        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
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
        task = self._in_flight.pop(task_id, None)
        if task:
            # Release capacity when task completes
            self._capacity.release(task_id)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
            else:
                # Max retries reached, release capacity
                self._capacity.release(task_id)
        return False

    @property
    def capacity_available(self) -> int:
        return self._capacity.available


class ResourceExhaustedError(Exception):
    """Raised when queue capacity is exhausted."""
    pass
