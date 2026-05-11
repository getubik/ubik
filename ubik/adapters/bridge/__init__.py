"""Bridge adapters — how Ubik whispers to humans."""
from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from ubik.core.config import UbikConfig

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
    "bridge_from_config",
]


def bridge_from_config(cfg: "UbikConfig") -> Bridge:
    """Resolve a Bridge from ``UbikConfig.bridge.type``.

    Single-dispatch on the validated enum value. Loader rejects unknown
    types at YAML-load time (see SUPPORTED_BRIDGE_TYPES), so the only
    branch we need today is telegram.
    """
    btype = cfg.bridge.type
    if btype == "telegram":
        return telegram_from_config({
            "token_env": cfg.bridge.token_env,
            "chat_id_env": cfg.bridge.chat_id_env,
            "approver_chat_ids": cfg.bridge.approver_chat_ids,
        })
    raise RuntimeError(
        f"bridge.type={btype!r} reached the factory but is not in the "
        "supported set. This is a bug — the loader should have rejected "
        "it. See ubik/core/config.py SUPPORTED_BRIDGE_TYPES."
    )
