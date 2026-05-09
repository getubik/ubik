"""Bridge adapters — how Ubik whispers to humans."""
from .base import (
    ApprovalEvent,
    Bridge,
    Decision,
    NotifyMessage,
    ProposalMessage,
    Severity,
)
from .telegram import (
    TelegramBridge,
    TelegramConfig,
    telegram_from_config,
    telegram_from_env,
)

__all__ = [
    "ApprovalEvent",
    "Bridge",
    "Decision",
    "NotifyMessage",
    "ProposalMessage",
    "Severity",
    "TelegramBridge",
    "TelegramConfig",
    "telegram_from_config",
    "telegram_from_env",
]
