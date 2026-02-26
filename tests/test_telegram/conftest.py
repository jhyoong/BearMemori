"""Shared test fixtures for BearMemori telegram service tests."""

import os
import sys

# Add telegram directory to path so tg_gateway module is importable
telegram_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "telegram",
)
if telegram_dir not in sys.path:
    sys.path.insert(0, telegram_dir)
