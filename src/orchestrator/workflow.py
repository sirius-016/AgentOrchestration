"""Workflow Manager -- Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"
    BLOCKED = "blocked"


class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_ROLLED_BACK = "partially_rolled_back"
    BLOCKED = "blocked"


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, retries: int = 0,
                 timeout: int = 300, compensate: Optional[Callable] = None):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.compensate = compensate  # rollback/compensation handler
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None
        self.depends_on: Set[str] = set()  # step IDs this step depends on


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = WorkflowStatus.PENDING
        self._rolled_back_steps: Set[str] = set()  # steps that were rolled back
        self._blocked_steps: Set[str] = set()  # steps blocked due to rollback

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def _block_downstream(self, failed_step: WorkflowStep) -> None:
        """Block all downstream steps that depend on the failed/rolled-back step.

        After a partial rollback, downstream steps cannot safely execute
        because their inputs may be inconsistent. This method marks them
        as blocked and records the dependency chain for audit.
        """
        for step in self.steps:
            if step.status not in (StepStatus.PENDING,):
                continue
            # Block if this step directly or transitively depends on the failed step
            if self._depends_on(step, failed_step.id):
                step.status = StepStatus.BLOCKED
                self._blocked_steps.add(step.id)
                logger.info(
                    f"Blocked downstream step '{step.name}' ({step.id}) "
                    f"due to rollback of '{failed_step.name}' ({failed_step.id})"
                )

    def _depends_on(self, step: WorkflowStep, target_id: str, visited: Optional[Set[str]] = None) -> bool:
        """Check if a step directly or transitively depends on a target step."""
        if visited is None:
            visited = set()
        if step.id in visited:
            return False
        visited.add(step.id)

        # Direct dependency
        if target_id in step.depends_on:
            return True

        # Transitive: check if any of this step's dependencies depend on target
        for dep_id in step.depends_on:
            dep_step = self._step_map.get(dep_id)
            if dep_step and self._depends_on(dep_step, target_id, visited):
                return True

        # Implicit: if target comes before this step in the list and has no
        # explicit dependency graph, we use position-based ordering
        target_idx = next((i for i, s in enumerate(self.steps) if s.id == target_id), None)
        step_idx = next((i for i, s in enumerate(self.steps) if s.id == step.id), None)
        if target_idx is not None and step_idx is not None and target_idx < step_idx:
            return True

        return False

    def _compensate_step(self, step: WorkflowStep) -> bool:
        """Run the compensation (rollback) handler for a step.

        Returns True if compensation succeeded, False otherwise.
        """
        if step.compensate:
            try:
                step.compensate()
                step.status = StepStatus.ROLLED_BACK
                self._rolled_back_steps.add(step.id)
                logger.info(f"Compensated step '{step.name}' ({step.id})")
                return True
            except Exception as e:
                logger.error(f"Compensation failed for step '{step.name}': {e}")
                return False
        else:
            step.status = StepStatus.ROLLED_BACK
            self._rolled_back_steps.add(step.id)
            logger.info(f"Marked step '{step.name}' as rolled back (no compensation handler)")
            return True


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str) -> bool:
        """Execute a workflow with compensating action support.

        If a step fails and has a compensation handler, we roll back completed
        steps in reverse order and block all downstream steps to prevent
        execution on inconsistent state.
        """
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = WorkflowStatus.RUNNING
        completed_steps = []

        for step in workflow.steps:
            # Skip steps that are already blocked
            if step.status == StepStatus.BLOCKED:
                logger.info(f"Skipping blocked step '{step.name}'")
                continue

            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
                completed_steps.append(step)
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                logger.error(f"Step '{step.name}' failed: {e}")

                # Compensating actions: roll back completed steps in reverse order
                for prev_step in reversed(completed_steps):
                    workflow._compensate_step(prev_step)

                # Block all downstream steps to prevent execution on inconsistent state
                workflow._block_downstream(step)

                workflow.status = WorkflowStatus.PARTIALLY_ROLLED_BACK
                logger.info(
                    f"Workflow '{workflow.name}' partially rolled back after "
                    f"failure in step '{step.name}'. {len(workflow._blocked_steps)} "
                    f"downstream steps blocked."
                )
                return False

        workflow.status = WorkflowStatus.COMPLETED
        return True
