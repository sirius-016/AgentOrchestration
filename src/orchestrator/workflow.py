"""Workflow Manager -- Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BranchOutputError(Exception):
    """Raised when branch output names violate uniqueness constraints."""
    pass


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, output_name: Optional[str] = None, retries: int = 0, timeout: int = 300):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.output_name = output_name
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


def validate_branch_outputs(steps: List[WorkflowStep]) -> None:
    """Validate that branch output names are unique across workflow steps.

    Raises BranchOutputError if duplicate output_name values are found.
    Steps with output_name=None are ignored (no branch output).
    """
    seen: Dict[str, str] = {}
    for step in steps:
        if step.output_name is None:
            continue
        if step.output_name in seen:
            raise BranchOutputError(
                "Duplicate branch output name '" + step.output_name + "' "
                "found in steps '" + seen[step.output_name] + "' and '" + step.name + "'"
            )
        seen[step.output_name] = step.name


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        validate_branch_outputs(self.steps + [step])
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "", steps: Optional[List[WorkflowStep]] = None) -> Workflow:
        workflow = Workflow(name, description)
        if steps:
            validate_branch_outputs(steps)
            for step in steps:
                workflow.steps.append(step)
                workflow._step_map[step.id] = step
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True
