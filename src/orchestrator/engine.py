"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler
from src.orchestrator.checkpoint import CheckpointStore, CheckpointRecord

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }
        # Checkpoint store for idempotent checkpoint persistence
        self.checkpoint_store = CheckpointStore()

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
            task = await self.scheduler.dequeue()
            if task:
                asyncio.create_task(self._execute_task(task))
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        logger.info("Orchestration engine stopped")

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        agent_id = task["target_agent"]
        step_id = task.get("step_id", "default")
        attempt_id = task.get("attempt_id", str(uuid.uuid4()))
        
        logger.info(f"Executing task {task_id} on agent {agent_id} (step={step_id}, attempt={attempt_id})")

        for hook in self._hooks["pre_execute"]:
            await hook(task)

        try:
            agent = self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            self.registry.update_status(agent_id, AgentStatus.RUNNING)
            
            # Try to resume from checkpoint if exists
            checkpoint = self.checkpoint_store.read(task_id, step_id, attempt_id)
            if checkpoint:
                logger.info(f"Resuming task {task_id} from checkpoint")
                task["checkpoint_data"] = checkpoint.content
            
            result = await asyncio.wait_for(
                self._run_agent_task(agent, task),
                timeout=self.agent_timeout,
            )
            
            # Write checkpoint with idempotent key
            checkpoint_content = {
                "result": result,
                "status": "completed",
                "agent_id": agent_id,
            }
            self.checkpoint_store.write(task_id, step_id, attempt_id, checkpoint_content)
            
            self.registry.update_status(agent_id, AgentStatus.PAUSED)

            for hook in self._hooks["post_execute"]:
                await hook(task, result)

            logger.info(f"Task {task_id} completed successfully")

        except asyncio.TimeoutError:
            logger.error(f"Task {task_id} timed out after {self.agent_timeout}s")
            # Write timeout checkpoint for retry resumption
            timeout_content = {
                "status": "timeout",
                "agent_id": agent_id,
                "timeout_at": asyncio.get_event_loop().time(),
            }
            try:
                self.checkpoint_store.write(task_id, step_id, attempt_id, timeout_content)
            except Exception as e:
                logger.warning(f"Failed to write timeout checkpoint: {e}")
            
            for hook in self._hooks["on_error"]:
                await hook(task, "timeout")
                
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            for hook in self._hooks["on_error"]:
                await hook(task, e)

    async def _run_agent_task(self, agent: Dict, task: Dict) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._execute_in_thread,
            agent,
            task,
        )

    def _execute_in_thread(self, agent: Dict, task: Dict) -> Any:
        return {"status": "completed", "output": f"Task {task['id']} processed by {agent['name']}"}

    def get_checkpoint(
        self,
        task_id: str,
        step_id: str,
        attempt_id: str,
    ) -> Optional[CheckpointRecord]:
        """Retrieve a checkpoint by its deterministic key."""
        return self.checkpoint_store.read(task_id, step_id, attempt_id)

    def resume_from_checkpoint(
        self,
        task_id: str,
        step_id: str,
        attempt_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Resume task execution from a checkpoint if it exists."""
        checkpoint = self.checkpoint_store.read(task_id, step_id, attempt_id)
        if checkpoint:
            logger.info(f"Resuming task {task_id} from checkpoint (step={step_id}, attempt={attempt_id})")
            return checkpoint.content
        return None
