"""Executor adapters — how Ubik turns proposals into code changes."""
from .base import Executor, ExecutionResult, ExecutorOutcome, ExecutorTask
from .aider import AiderConfig, AiderExecutor

__all__ = [
    "Executor",
    "ExecutionResult",
    "ExecutorOutcome",
    "ExecutorTask",
    "AiderConfig",
    "AiderExecutor",
]
