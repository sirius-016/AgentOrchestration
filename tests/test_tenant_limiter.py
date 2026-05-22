"""Tests for per-tenant concurrency limiter."""

import sys
sys.path.insert(0, "src")

import unittest
import threading
from src.scheduler.tenant_limiter import (
    TenantConcurrencyLimiter,
    TenantConcurrencyError,
    TenantSlot,
    MAX_TENANT_CONCURRENCY,
)


class TestAcquireRelease(unittest.TestCase):
    def setUp(self):
        self.limiter = TenantConcurrencyLimiter(default_max=3)
    
    def test_acquire_within_limit(self):
        self.limiter.acquire("t1")
        self.limiter.acquire("t1")
        self.assertEqual(self.limiter.get_usage("t1")["active"], 2)
    
    def test_acquire_at_limit(self):
        for _ in range(3):
            self.limiter.acquire("t1")
        self.assertEqual(self.limiter.get_usage("t1")["active"], 3)
    
    def test_acquire_exceeds_raises(self):
        for _ in range(3):
            self.limiter.acquire("t1")
        with self.assertRaises(TenantConcurrencyError) as ctx:
            self.limiter.acquire("t1")
        self.assertEqual(ctx.exception.current, 3)
        self.assertEqual(ctx.exception.maximum, 3)
        self.assertIn("t1", str(ctx.exception))
    
    def test_release_frees_slot(self):
        for _ in range(3):
            self.limiter.acquire("t1")
        count = self.limiter.release("t1")
        self.assertEqual(count, 2)
        # Can acquire again
        self.limiter.acquire("t1")
        self.assertEqual(self.limiter.get_usage("t1")["active"], 3)
    
    def test_release_nonexistent_returns_zero(self):
        self.assertEqual(self.limiter.release("nonexistent"), 0)


class TestTenantIsolation(unittest.TestCase):
    def setUp(self):
        self.limiter = TenantConcurrencyLimiter(default_max=2)
    
    def test_tenants_independent(self):
        self.limiter.acquire("t1")
        self.limiter.acquire("t1")
        # t1 at max, t2 should still work
        self.limiter.acquire("t2")
        self.assertEqual(self.limiter.get_usage("t1")["active"], 2)
        self.assertEqual(self.limiter.get_usage("t2")["active"], 1)


class TestSetMax(unittest.TestCase):
    def setUp(self):
        self.limiter = TenantConcurrencyLimiter(default_max=2)
    
    def test_increase_limit(self):
        self.limiter.acquire("t1")
        self.limiter.acquire("t1")
        self.limiter.set_max("t1", 5)
        # Should be able to acquire more
        self.limiter.acquire("t1")
        self.assertEqual(self.limiter.get_usage("t1")["active"], 3)
    
    def test_decrease_limit(self):
        self.limiter.acquire("t1")
        self.limiter.set_max("t1", 1)
        with self.assertRaises(TenantConcurrencyError):
            self.limiter.acquire("t1")
    
    def test_set_max_minimum_one(self):
        with self.assertRaises(ValueError):
            self.limiter.set_max("t1", 0)
    
    def test_default_max(self):
        self.assertEqual(self.limiter.get_usage("new_tenant")["max"], 2)


class TestReset(unittest.TestCase):
    def setUp(self):
        self.limiter = TenantConcurrencyLimiter(default_max=3)
    
    def test_reset_clears_count(self):
        self.limiter.acquire("t1")
        self.limiter.reset("t1")
        self.assertEqual(self.limiter.get_usage("t1")["active"], 0)
    
    def test_reset_nonexistent_ok(self):
        self.limiter.reset("nonexistent")  # should not raise


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_acquires(self):
        limiter = TenantConcurrencyLimiter(default_max=10)
        errors = []
        
        def acquire_many():
            try:
                for _ in range(5):
                    limiter.acquire("t1")
            except TenantConcurrencyError:
                errors.append(True)
        
        threads = [threading.Thread(target=acquire_many) for _ in range(3)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        # Should have some errors since 3 threads x 5 = 15 but max is 10
        self.assertTrue(len(errors) > 0)
        self.assertEqual(limiter.get_usage("t1")["active"], 10)


class TestErrorFormatting(unittest.TestCase):
    def test_error_message(self):
        err = TenantConcurrencyError(tenant_id="acme", current=5, maximum=3)
        msg = str(err)
        self.assertIn("acme", msg)
        self.assertIn("5/3", msg)
        self.assertIn("active runs", msg)


if __name__ == "__main__":
    unittest.main()
