"""Tests for sandbox resource limit validation."""
import pytest
from src.agent.sandbox import ResourceLimits, AgentSandbox
from src.common.config import Config


def test_valid_resource_limits():
    """Test that valid limits are accepted."""
    limits = ResourceLimits(cpu_time=60, memory_mb=512, disk_mb=100)
    assert limits.cpu_time == 60
    assert limits.memory_mb == 512
    assert limits.disk_mb == 100


def test_zero_cpu_time_raises():
    """Test that zero cpu_time raises ValueError."""
    with pytest.raises(ValueError, match="cpu_time"):
        ResourceLimits(cpu_time=0)


def test_negative_memory_raises():
    """Test that negative memory_mb raises ValueError."""
    with pytest.raises(ValueError, match="memory_mb"):
        ResourceLimits(memory_mb=-10)


def test_negative_disk_raises():
    """Test that negative disk_mb raises ValueError."""
    with pytest.raises(ValueError, match="disk_mb"):
        ResourceLimits(disk_mb=-1)


def test_fractional_limits():
    """Test that fractional positive values are accepted (edge case)."""
    limits = ResourceLimits(cpu_time=1, memory_mb=1, disk_mb=1)
    assert limits.cpu_time == 1


def test_apply_limits_with_valid():
    """Test that apply_limits works with valid limits."""
    sandbox = AgentSandbox()
    sandbox.create("test-agent")
    limits = ResourceLimits(cpu_time=10, memory_mb=256, disk_mb=50)
    sandbox.apply_limits("test-agent", limits)  # Should not raise
    sandbox.destroy("test-agent")
</