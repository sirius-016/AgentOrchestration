"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union, Tuple
from uuid import uuid4
import re


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TimeoutUnit(Enum):
    """Supported timeout units."""
    MILLISECONDS = "ms"
    SECONDS = "s"
    MINUTES = "m"
    HOURS = "h"


# Unit conversion factors to seconds
UNIT_TO_SECONDS = {
    TimeoutUnit.MILLISECONDS: 0.001,
    TimeoutUnit.SECONDS: 1,
    TimeoutUnit.MINUTES: 60,
    TimeoutUnit.HOURS: 3600,
}


class TimeoutSpec:
    """Represents a timeout specification with value and unit."""
    
    def __init__(self, value: Union[int, float], unit: TimeoutUnit = TimeoutUnit.SECONDS):
        self.value = value
        self.unit = unit
    
    def to_seconds(self) -> float:
        """Convert timeout to seconds."""
        return self.value * UNIT_TO_SECONDS[self.unit]
    
    @classmethod
    def from_string(cls, timeout_str: str) -> 'TimeoutSpec':
        """Parse timeout from string like '5000ms', '5s', '5m', '5h'."""
        pattern = r'^(\d+(?:\.\d+)?)\s*(ms|s|m|h)$'
        match = re.match(pattern, timeout_str.strip())
        if not match:
            raise ValueError(
                f"Invalid timeout format: '{timeout_str}'. "
                f"Expected format like '5000ms', '5s', '5m', or '5h'."
            )
        
        value = float(match.group(1))
        unit_str = match.group(2)
        
        unit_map = {
            'ms': TimeoutUnit.MILLISECONDS,
            's': TimeoutUnit.SECONDS,
            'm': TimeoutUnit.MINUTES,
            'h': TimeoutUnit.HOURS,
        }
        
        return cls(value, unit_map[unit_str])
    
    def __repr__(self):
        return f"TimeoutSpec({self.value}, {self.unit.value})"


def validate_timeout(timeout: Union[int, float, str, TimeoutSpec]) -> TimeoutSpec:
    """
    Validate and normalize timeout specification.
    
    Args:
        timeout: Timeout as int (seconds), float (seconds), string ('5s', '5m', etc.),
                 or TimeoutSpec object.
    
    Returns:
        TimeoutSpec object with validated timeout.
    
    Raises:
        ValueError: If timeout is invalid or negative.
    """
    if isinstance(timeout, TimeoutSpec):
        validated = timeout
    elif isinstance(timeout, (int, float)):
        if timeout < 0:
            raise ValueError(f"Timeout must be >= 0, got {timeout}")
        validated = TimeoutSpec(timeout, TimeoutUnit.SECONDS)
    elif isinstance(timeout, str):
        validated = TimeoutSpec.from_string(timeout)
    else:
        raise ValueError(
            f"Timeout must be int, float, string, or TimeoutSpec, got {type(timeout)}"
        )
    
    if validated.value < 0:
        raise ValueError(f"Timeout must be >= 0, got {validated.value}")
    
    return validated


def duration_parser(timeout_spec: TimeoutSpec) -> float:
    """
    Parse timeout specification and return duration in seconds.
    
    Args:
        timeout_spec: TimeoutSpec object.
    
    Returns:
        Duration in seconds as float.
    """
    return timeout_spec.to_seconds()


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, 
                 retries: int = 0, 
                 timeout: Union[int, float, str, TimeoutSpec] = 300):
        """
        Initialize a workflow step.
        
        Args:
            name: Step name.
            handler: Callable to execute.
            retries: Number of retries (default 0).
            timeout: Timeout specification. Can be:
                     - int/float: timeout in seconds (backwards compatible)
                     - str: timeout string like '5000ms', '5s', '5m', '5h'
                     - TimeoutSpec: explicit timeout specification
        """
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        
        # Validate and normalize timeout
        self._timeout_spec = validate_timeout(timeout)
        self.timeout = self._timeout_spec.to_seconds()  # Store in seconds for execution
        
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None
    
    def get_timeout_string(self) -> str:
        """Return human-readable timeout string."""
        return f"{self._timeout_spec.value}{self._timeout_spec.unit.value}"


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING
        self._validated = False

    def add_step(self, step: WorkflowStep) -> "Workflow":
        """
        Add a step to the workflow.
        
        Args:
            step: WorkflowStep to add.
        
        Returns:
            Self for method chaining.
        
        Raises:
            ValueError: If step has conflicting or invalid timeout.
        """
        # Validate step timeout
        if step.timeout < 0:
            raise ValueError(
                f"Step '{step.name}' has invalid timeout: {step.timeout}s. "
                f"Timeout must be >= 0."
            )
        
        # Check for conflicting timeout units (if step was created with string timeout)
        if hasattr(step, '_timeout_spec'):
            spec = step._timeout_spec
            # Additional validation could be added here for specific conflict detection
            pass
        
        self.steps.append(step)
        self._step_map[step.id] = step
        self._validated = False  # Invalidate validation cache
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)
    
    def validate(self) -> List[str]:
        """
        Validate the workflow definition.
        
        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []
        
        # Check for duplicate step names
        step_names = [step.name for step in self.steps]
        duplicates = [name for name in step_names if step_names.count(name) > 1]
        if duplicates:
            unique_duplicates = list(set(duplicates))
            errors.append(f"Duplicate step names found: {unique_duplicates}")
        
        # Validate each step's timeout
        for step in self.steps:
            if step.timeout < 0:
                errors.append(
                    f"Step '{step.name}' has invalid timeout: {step.timeout}s"
                )
        
        self._validated = len(errors) == 0
        return errors


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        """
        Create a new workflow.
        
        Args:
            name: Workflow name.
            description: Optional description.
        
        Returns:
            New Workflow object.
        """
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def validate_workflow(self, workflow_id: str) -> Tuple[bool, List[str]]:
        """
        Validate a workflow before execution.
        
        Args:
            workflow_id: ID of workflow to validate.
        
        Returns:
            Tuple of (is_valid, error_messages).
        """
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False, [f"Workflow {workflow_id} not found"]
        
        errors = workflow.validate()
        return len(errors) == 0, errors

    def execute_workflow(self, workflow_id: str) -> bool:
        """
        Execute a workflow with pre-dispatch validation.
        
        Args:
            workflow_id: ID of workflow to execute.
        
        Returns:
            True if workflow completed successfully, False otherwise.
        
        Raises:
            ValueError: If workflow definition is invalid.
        """
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        # Pre-dispatch validation
        is_valid, errors = self.validate_workflow(workflow_id)
        if not is_valid:
            raise ValueError(
                f"Cannot execute workflow '{workflow.name}': "
                f"validation failed: {errors}"
            )

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                # Pass timeout to handler if it accepts a timeout parameter
                import inspect
                sig = inspect.signature(step.handler)
                if 'timeout' in sig.parameters:
                    result = step.handler(timeout=step.timeout)
                else:
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
