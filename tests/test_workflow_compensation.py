"""Tests for workflow compensation and downstream blocking (#68)."""

import pytest
from src.orchestrator.workflow import (
    WorkflowManager, WorkflowStep, StepStatus, WorkflowStatus
)


class TestWorkflowCompensation:
    def test_successful_workflow_no_rollback(self):
        """All steps succeed - no compensation needed."""
        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step1", handler=lambda: "ok1"))
        wf.add_step(WorkflowStep("step2", handler=lambda: "ok2"))

        result = manager.execute_workflow(wf.id)
        assert result is True
        assert wf.status == WorkflowStatus.COMPLETED
        assert all(s.status == StepStatus.COMPLETED for s in wf.steps)

    def test_failed_step_triggers_rollback(self):
        """Failing step should trigger compensation of completed steps."""
        compensated = []

        def compensate1():
            compensated.append("step1")

        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step1", handler=lambda: "ok1", compensate=compensate1))
        wf.add_step(WorkflowStep("step2", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))

        result = manager.execute_workflow(wf.id)
        assert result is False
        assert wf.status == WorkflowStatus.PARTIALLY_ROLLED_BACK
        assert compensated == ["step1"]

    def test_downstream_blocked_after_rollback(self):
        """Steps after a failed step should be blocked, not pending."""
        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step1", handler=lambda: "ok1"))
        wf.add_step(WorkflowStep("step2", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))
        wf.add_step(WorkflowStep("step3", handler=lambda: "ok3"))

        result = manager.execute_workflow(wf.id)
        assert result is False
        assert wf.steps[0].status == StepStatus.ROLLED_BACK  # compensated
        assert wf.steps[1].status == StepStatus.FAILED
        assert wf.steps[2].status == StepStatus.BLOCKED  # downstream blocked

    def test_compensation_order_is_reversed(self):
        """Compensation should run in reverse order of completion."""
        order = []

        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step1", handler=lambda: "ok1",
                                  compensate=lambda: order.append(1)))
        wf.add_step(WorkflowStep("step2", handler=lambda: "ok2",
                                  compensate=lambda: order.append(2)))
        wf.add_step(WorkflowStep("step3", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))

        manager.execute_workflow(wf.id)
        assert order == [2, 1]  # reversed

    def test_no_compensation_handler_still_marks_rolled_back(self):
        """Steps without compensation handlers should still be marked as rolled back."""
        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step1", handler=lambda: "ok1"))  # no compensate
        wf.add_step(WorkflowStep("step2", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))

        manager.execute_workflow(wf.id)
        assert wf.steps[0].status == StepStatus.ROLLED_BACK

    def test_blocked_workflow_status(self):
        """Workflow with blocked steps should have PARTIALLY_ROLLED_BACK status."""
        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step1", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))
        wf.add_step(WorkflowStep("step2", handler=lambda: "ok2"))

        manager.execute_workflow(wf.id)
        assert wf.status == WorkflowStatus.PARTIALLY_ROLLED_BACK
        assert wf.steps[1].status == StepStatus.BLOCKED

    def test_explicit_dependency_blocking(self):
        """Steps with explicit depends_on should be blocked when dependency fails."""
        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        step1 = WorkflowStep("step1", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        step2 = WorkflowStep("step2", handler=lambda: "ok2")
        step2.depends_on.add(step1.id)
        wf.add_step(step1)
        wf.add_step(step2)

        manager.execute_workflow(wf.id)
        assert step2.status == StepStatus.BLOCKED

    def test_compensation_failure_does_not_crash(self):
        """If compensation itself fails, workflow should still complete gracefully."""
        def bad_compensate():
            raise RuntimeError("compensation failed")

        manager = WorkflowManager()
        wf = manager.create_workflow("test-wf")
        wf.add_step(WorkflowStep("step1", handler=lambda: "ok1", compensate=bad_compensate))
        wf.add_step(WorkflowStep("step2", handler=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))

        # Should not raise
        result = manager.execute_workflow(wf.id)
        assert result is False
