"""Tests for archived-run lifecycle guard (Issue #1692)."""

import asyncio
import pytest

from src.orchestrator.engine import (
    ArchivedRunError,
    OrchestrationEngine,
    RunLifecycle,
)


class TestArchivedRunGuard:
    """Verify that events for archived runs are rejected."""

    def test_archive_run_transitions_lifecycle(self):
        engine = OrchestrationEngine()
        run_id = "run-abc"
        engine.archive_run(run_id)
        assert run_id in engine._archived_runs

    def test_check_archived_raises_for_archived_run(self):
        engine = OrchestrationEngine()
        run_id = "run-xyz"
        engine.archive_run(run_id)
        with pytest.raises(ArchivedRunError):
            engine._check_archived(run_id)

    def test_check_archived_passes_for_active_run(self):
        engine = OrchestrationEngine()
        # Should not raise
        engine._check_archived("nonexistent-run")

    @pytest.mark.asyncio
    async def test_execute_task_rejects_archived_run(self):
        engine = OrchestrationEngine()
        run_id = "archived-run-1"
        engine.archive_run(run_id)

        task = {"id": run_id, "target_agent": "some-agent"}
        with pytest.raises(ArchivedRunError):
            await engine._execute_task(task)

    @pytest.mark.asyncio
    async def test_execute_task_accepts_active_run(self):
        """Active (non-archived) runs should still be processed normally."""
        engine = OrchestrationEngine()
        # Register a minimal agent so the task can proceed to agent lookup
        # (it will fail at registry.get, which is fine — we just want to
        # confirm ArchivedRunError is NOT raised)
        task = {"id": "active-run-1", "target_agent": "some-agent"}
        # Should not raise ArchivedRunError; will raise ValueError for
        # missing agent instead, which proves the guard was passed.
        with pytest.raises((ValueError, TypeError)):
            await engine._execute_task(task)

    def test_multiple_runs_can_be_archived(self):
        engine = OrchestrationEngine()
        for i in range(5):
            engine.archive_run(f"run-{i}")
        assert len(engine._archived_runs) == 5
        for i in range(5):
            with pytest.raises(ArchivedRunError):
                engine._check_archived(f"run-{i}")

    def test_archived_run_error_message(self):
        engine = OrchestrationEngine()
        engine.archive_run("run-1")
        with pytest.raises(ArchivedRunError) as exc_info:
            engine._check_archived("run-1")
        assert "run-1" in str(exc_info.value)
        assert RunLifecycle.ARCHIVED.value in str(exc_info.value)
