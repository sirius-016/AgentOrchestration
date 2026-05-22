"""Per-tenant concurrency limiter for the scheduler."""

import os
import time
import threading
from typing import Dict, Optional
from dataclasses import dataclass, field


# Max concurrent runs per tenant (default 10)
DEFAULT_MAX_CONCURRENCY = 10
MAX_TENANT_CONCURRENCY = int(os.environ.get("MAX_TENANT_CONCURRENCY", DEFAULT_MAX_CONCURRENCY))


@dataclass
class TenantSlot:
    """Tracks active run slots for a single tenant."""
    tenant_id: str
    active_count: int = 0
    max_concurrency: int = MAX_TENANT_CONCURRENCY
    queue_time: float = 0.0  # timestamp of last enqueue wait start


class TenantConcurrencyLimiter:
    """Thread-safe per-tenant concurrency enforcement.
    
    Each tenant has a configurable max concurrent run limit.
    Attempts to exceed the limit raise TenantConcurrencyError.
    """
    
    def __init__(self, default_max: int = MAX_TENANT_CONCURRENCY):
        self._default_max = default_max
        self._tenants: Dict[str, TenantSlot] = {}
        self._lock = threading.Lock()
    
    def acquire(self, tenant_id: str) -> None:
        """Acquire a concurrency slot for the tenant.
        
        Raises:
            TenantConcurrencyError: If tenant is at max concurrency.
        """
        with self._lock:
            slot = self._get_or_create(tenant_id)
            if slot.active_count >= slot.max_concurrency:
                slot.queue_time = time.time()
                raise TenantConcurrencyError(
                    tenant_id=tenant_id,
                    current=slot.active_count,
                    maximum=slot.max_concurrency,
                )
            slot.active_count += 1
    
    def release(self, tenant_id: str) -> int:
        """Release a concurrency slot. Returns new active count."""
        with self._lock:
            slot = self._tenants.get(tenant_id)
            if slot is None:
                return 0
            if slot.active_count > 0:
                slot.active_count -= 1
            return slot.active_count
    
    def set_max(self, tenant_id: str, max_concurrency: int) -> None:
        """Set per-tenant max concurrency override."""
        if max_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency}")
        with self._lock:
            slot = self._get_or_create(tenant_id)
            slot.max_concurrency = max_concurrency
    
    def get_usage(self, tenant_id: str) -> dict:
        """Get current usage for a tenant."""
        with self._lock:
            slot = self._tenants.get(tenant_id)
            if slot is None:
                return {"tenant_id": tenant_id, "active": 0, "max": self._default_max}
            return {
                "tenant_id": tenant_id,
                "active": slot.active_count,
                "max": slot.max_concurrency,
            }
    
    def reset(self, tenant_id: str) -> None:
        """Reset counter for a tenant."""
        with self._lock:
            self._tenants.pop(tenant_id, None)
    
    def _get_or_create(self, tenant_id: str) -> TenantSlot:
        slot = self._tenants.get(tenant_id)
        if slot is None:
            slot = TenantSlot(tenant_id=tenant_id, max_concurrency=self._default_max)
            self._tenants[tenant_id] = slot
        return slot


class TenantConcurrencyError(Exception):
    """Raised when a tenant exceeds its concurrency limit."""
    
    def __init__(self, tenant_id: str, current: int, maximum: int):
        self.tenant_id = tenant_id
        self.current = current
        self.maximum = maximum
        super().__init__(
            f"Tenant {tenant_id} has {current}/{maximum} active runs. "
            f"Reduce concurrent runs or request a higher limit."
        )


__all__ = [
    "MAX_TENANT_CONCURRENCY",
    "TenantSlot",
    "TenantConcurrencyLimiter",
    "TenantConcurrencyError",
]
