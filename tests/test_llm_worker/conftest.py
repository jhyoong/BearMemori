"""Configure path for llm_worker tests."""

import os
import sys

# Ensure correct llm_worker path is used - prioritize local version over worktree
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_llm_worker_path = os.path.join(PROJECT_ROOT, "llm_worker")
if _llm_worker_path not in sys.path:
    sys.path.insert(0, _llm_worker_path)

# Add shared path for redis_streams
_shared_path = os.path.join(PROJECT_ROOT, "shared")
if _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)
