"""Tests for task decorator validation."""
import pytest
import asyncio
from src.sdk.decorators import task


def test_zero_timeout_raises():
    """Test that zero timeout raises ValueError."""
    with pytest.raises(ValueError, match="timeout"):
        @task(timeout=0)
        async def my_task():
            pass


def test_negative_timeout_raises():
    """Test that negative timeout raises ValueError."""
    with pytest.raises(ValueError, match="timeout"):
        @task(timeout=-1)
        async def my_task():
            pass


def test_negative_retries_raises():
    """Test that negative retries raises ValueError."""
    with pytest.raises(ValueError, match="retries"):
        @task(retries=-1)
        async def my_task():
            pass


def test_valid_timeout_accepted():
    """Test that valid timeout is accepted."""
    @task(timeout=30)
    async def my_task():
        pass
    assert my_task.__task_config__["timeout"] == 30


def test_timeout_zero_or_negative_behavior():
    """Verify timeout <= 0 would cause asyncio.wait_for to fail immediately."""
    import asyncio
    
    async def quick():
        return "done"
    
    # timeout=0 would immediately timeout
    with pytest.raises(asyncio.TimeoutError):
        asyncio.get_event_loop().run_until_complete(
            asyncio.wait_for(quick(), timeout=0)
        )
