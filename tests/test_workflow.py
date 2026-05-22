"""Tests for branch output name enforcement (Issue #1701)."""

import pytest
from orchestrator.workflow import (
    BranchOutputError,
    WorkflowStep,
    Workflow,
    WorkflowManager,
    validate_branch_outputs,
)


def handler_a():
    return "a"


def handler_b():
    return "b"


def handler_c():
    return "c"


class TestValidateBranchOutputs:
    def test_no_output_names_valid(self):
        steps = [WorkflowStep("s1", handler_a), WorkflowStep("s2", handler_b)]
        validate_branch_outputs(steps)  # no error

    def test_unique_output_names_valid(self):
        steps = [
            WorkflowStep("s1", handler_a, output_name="out_a"),
            WorkflowStep("s2", handler_b, output_name="out_b"),
        ]
        validate_branch_outputs(steps)  # no error

    def test_duplicate_output_names_raises(self):
        steps = [
            WorkflowStep("s1", handler_a, output_name="result"),
            WorkflowStep("s2", handler_b, output_name="result"),
        ]
        with pytest.raises(BranchOutputError, match="Duplicate branch output name 'result'"):
            validate_branch_outputs(steps)

    def test_mixed_none_and_duplicate_raises(self):
        steps = [
            WorkflowStep("s1", handler_a, output_name=None),
            WorkflowStep("s2", handler_b, output_name="data"),
            WorkflowStep("s3", handler_c, output_name="data"),
        ]
        with pytest.raises(BranchOutputError):
            validate_branch_outputs(steps)

    def test_empty_steps_valid(self):
        validate_branch_outputs([])


class TestWorkflowAddStep:
    def test_add_step_duplicate_output_rejected(self):
        wf = Workflow("test_wf")
        wf.add_step(WorkflowStep("s1", handler_a, output_name="out"))
        with pytest.raises(BranchOutputError):
            wf.add_step(WorkflowStep("s2", handler_b, output_name="out"))

    def test_add_step_unique_output_accepted(self):
        wf = Workflow("test_wf")
        wf.add_step(WorkflowStep("s1", handler_a, output_name="out_a"))
        wf.add_step(WorkflowStep("s2", handler_b, output_name="out_b"))
        assert len(wf.steps) == 2


class TestWorkflowManagerCreateWorkflow:
    def test_create_with_duplicate_outputs_rejected(self):
        mgr = WorkflowManager()
        steps = [
            WorkflowStep("s1", handler_a, output_name="x"),
            WorkflowStep("s2", handler_b, output_name="x"),
        ]
        with pytest.raises(BranchOutputError):
            mgr.create_workflow("wf", steps=steps)

    def test_create_with_unique_outputs_accepted(self):
        mgr = WorkflowManager()
        steps = [
            WorkflowStep("s1", handler_a, output_name="x"),
            WorkflowStep("s2", handler_b, output_name="y"),
        ]
        wf = mgr.create_workflow("wf", steps=steps)
        assert len(wf.steps) == 2

    def test_create_without_steps(self):
        mgr = WorkflowManager()
        wf = mgr.create_workflow("wf")
        assert len(wf.steps) == 0
