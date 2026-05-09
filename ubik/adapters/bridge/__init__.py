"""Bridge adapters — how Ubik whispers to humans."""
from .base import Bridge, Decision, NotifyMessage, Severity
from .telegram import (
    TelegramBridge,
    TelegramConfig,
    telegram_from_config,
    telegram_from_env,
)

__all__ = [
    "Bridge",
    "Decision",
    "NotifyMessage",
    "Severity",
    "TelegramBridge",
    "TelegramConfig",
    "telegram_from_config",
    "telegram_from_env",
]
