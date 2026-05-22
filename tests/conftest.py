"""conftest — set up sys.path and mock Unix-only modules before any test runs."""
import sys
import os

# Ensure the repo root is on the import path
REPO_ROOT = r"C:\Users\ASUSS\Documents\GitHub\AgentOrchestration"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Mock the `resource` module (Unix-only) so src.agent.sandbox imports don't
# break the test collector on Windows.
if "resource" not in sys.modules:
    class _FakeResource:
        RLIMIT_NOFILE = 1
        RLIMIT_NPROC = 2
        RLIMIT_AS = 3

        @staticmethod
        def getrlimit(which):
            return (65536, 65536)

        @staticmethod
        def setrlimit(which, limits):
            pass

        @staticmethod
        def getrusage(who):
            class RUsage:
                ru_maxrss = 0
                ru_ixrss = 0
                ru_idrss = 0
                ru_isrss = 0
                ru_minflt = 0
                ru_majflt = 0
                ru_nswap = 0
                ru_inblock = 0
                ru_oublock = 0
                ru_msgsnd = 0
                ru_msgrcv = 0
                ru_nsignals = 0
                ru_nvcsw = 0
                ru_nivcsw = 0
            return RUsage()

    sys.modules["resource"] = _FakeResource()
