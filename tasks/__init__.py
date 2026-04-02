"""SOMER persistent task queue system.

Provides async task management backed by a Rust/Redis queue.
"""
from tasks.manager import AsyncTaskManager

__all__ = ["AsyncTaskManager"]
