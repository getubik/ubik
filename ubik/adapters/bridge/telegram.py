"""
Telegram bridge — the default Pssst! whisper channel.

Sprint 2 (this file): one-shot notify via the Bot API. No
incoming-callback handler yet — that comes when the executor wires
up the approve / reject / refine flow.

Why direct httpx instead of python-telegram-bot v21+:
  - We need only `sendMessage` for now; pulling in PTB's full
    Application + dispatcher loop is overkill for a fire-and-forget.
  - Sprint 2.2 (approval flow) will add PTB as an opt-in extra and
    use this adapter as the publish-side of a richer Bridge.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .base import Bridge, NotifyMessage, Severity

logger = logging.getLogger(__name__)


_SEVERITY_ICON = {
    Severity.LOW: "🤫",
    Severity.MEDIUM: "🤫",
    Severity.HIGH: "⚠️",
    Severity.CRITICAL: "🚨",
}


@dataclass(slots=True)
class TelegramConfig:
    """Configuration for the Telegram bridge."""

    bot_token: str
    """Bot token from @BotFather."""

    chat_ids: list[int]
    """Approver chat IDs. The first one is the primary; others are CC."""

    parse_mode: str = "HTML"
    """'HTML' (default) / 'MarkdownV2' / 'Markdown' (legacy).

    HTML is the default because MarkdownV2 reserves so many characters
    ('-', '.', '!', '+', '=', etc.) that any LLM-generated body breaks
    rendering without aggressive escaping. HTML only reserves three:
    < > &  — the renderer in this file handles those automatically.
    """

    # Telegram caps a single message at 4096 chars. We trim on send.
    max_message_chars: int = 3800


class TelegramBridge(Bridge):
    """Telegram Bot API bridge — async, httpx-based."""

    name = "telegram"

    def __init__(self, config: TelegramConfig) -> None:
        self.config = config
        self._endpoint = f"https://api.telegram.org/bot{config.bot_token}"

    async def notify(self, message: NotifyMessage) -> None:
        """Push the message to every configured chat. Errors per-chat are logged."""
        text = self._render(message)

        async with httpx.AsyncClient(timeout=15) as client:
            for chat_id in self.config.chat_ids:
                try:
                    resp = await client.post(
                        f"{self._endpoint}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": self.config.parse_mode,
                            "disable_web_page_preview": True,
                        },
                    )
                    if resp.status_code != 200:
                        # Telegram returns descriptive errors in the body.
                        logger.warning(
                            "Telegram send failed (chat=%s, status=%d): %s",
                            chat_id, resp.status_code, resp.text[:200],
                        )
                    else:
                        logger.info("Telegram notify sent → chat=%s", chat_id)
                except httpx.HTTPError as e:
                    logger.warning("Telegram notify network error (chat=%s): %s", chat_id, e)

    # ── rendering ────────────────────────────────────────────────────────

    def _render(self, message: NotifyMessage) -> str:
        icon = _SEVERITY_ICON.get(message.severity, "🤫")

        if self._is_html:
            head = f"{icon} <b>{_escape_html(message.title)}</b>"
            body = _markdown_lite_to_html(message.body_markdown)
            footer = (
                f"\n\n<i>{_escape_html(message.footer)}</i>"
                if message.footer else ""
            )
        elif self._is_md_v2:
            head = f"{icon} *{_escape_md_v2(message.title)}*"
            # Body trusts the LLM to be MarkdownV2-clean. Footer is small
            # enough to pre-escape safely.
            body = message.body_markdown
            footer = (
                f"\n\n_{_escape_md_v2(message.footer)}_"
                if message.footer else ""
            )
        else:  # plain
            head = f"{icon} {message.title}"
            body = message.body_markdown
            footer = f"\n\n{message.footer}" if message.footer else ""

        text = f"{head}\n\n{body}{footer}"

        # Trim if over Telegram's 4096-char hard cap.
        if len(text) > self.config.max_message_chars:
            cutoff = self.config.max_message_chars - 80
            text = text[:cutoff].rstrip() + "\n\n…(truncated)"
        return text

    @property
    def _is_html(self) -> bool:
        return self.config.parse_mode.lower() == "html"

    @property
    def _is_md_v2(self) -> bool:
        return self.config.parse_mode.lower() == "markdownv2"


# ── helpers ──────────────────────────────────────────────────────────────


# MarkdownV2 reserved set — must be backslash-escaped except inside
# pre/code blocks. Keep this conservative; over-escaping is harmless.
_MD_V2_RESERVED = r"_*[]()~`>#+-=|{}.!"


def _escape_md_v2(text: str) -> str:
    """Backslash-escape Telegram MarkdownV2 reserved characters."""
    out: list[str] = []
    for ch in text:
        if ch in _MD_V2_RESERVED:
            out.append("\\")
        out.append(ch)
    return "".join(out)


def _escape_html(text: str) -> str:
    """Escape the three Telegram-HTML reserved characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<![\*_])\*([^*\n]+?)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _markdown_lite_to_html(text: str) -> str:
    """Convert the small markdown subset our digest emits to Telegram-HTML.

    Telegram-HTML supports a handful of tags: <b>, <i>, <u>, <s>, <code>,
    <pre>, <a href=...>. Anything else is plain text. We only need:
      • **bold**     → <b>…</b>
      • *italic*     → <i>…</i>   (single-asterisk, not part of **)
      • `inline`     → <code>…</code>
      • [text](url)  → <a href="url">text</a>
    Everything else gets HTML-escaped so the message renders cleanly.
    """
    # Step 1: extract spans we want to preserve, replacing them with
    # placeholders so the bulk escape doesn't mangle their syntax.
    spans: list[str] = []

    def _stash(html_fragment: str) -> str:
        token = f"\x00{len(spans)}\x00"
        spans.append(html_fragment)
        return token

    text = _LINK_RE.sub(
        lambda m: _stash(f'<a href="{_escape_html(m.group(2))}">{_escape_html(m.group(1))}</a>'),
        text,
    )
    text = _INLINE_CODE_RE.sub(
        lambda m: _stash(f"<code>{_escape_html(m.group(1))}</code>"),
        text,
    )
    text = _BOLD_RE.sub(
        lambda m: _stash(f"<b>{_escape_html(m.group(1))}</b>"),
        text,
    )
    text = _ITALIC_RE.sub(
        lambda m: _stash(f"<i>{_escape_html(m.group(1))}</i>"),
        text,
    )

    # Step 2: escape the remaining plain text.
    text = _escape_html(text)

    # Step 3: restore the stashed HTML spans.
    for i, span in enumerate(spans):
        text = text.replace(f"\x00{i}\x00", span)

    return text


# ── factory used by CLI ──────────────────────────────────────────────────


def telegram_from_env(
    *,
    token_env: str = "TELEGRAM_BOT_TOKEN",
    chat_ids_env: str = "TELEGRAM_CHAT_ID",
) -> TelegramBridge:
    """Build a TelegramBridge from env vars — friendliest setup path.

    `chat_ids_env` may hold a single chat ID or a comma-separated list.
    """
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"missing env var: {token_env}")
    raw = os.environ.get(chat_ids_env, "").strip()
    if not raw:
        raise RuntimeError(f"missing env var: {chat_ids_env}")
    chat_ids = [int(x.strip()) for x in raw.split(",") if x.strip()]
    return TelegramBridge(TelegramConfig(bot_token=token, chat_ids=chat_ids))


def telegram_from_config(cfg: dict[str, Any]) -> TelegramBridge:
    """Build a TelegramBridge from the `bridge` block of ubik.yaml."""
    token_env = cfg.get("token_env", "TELEGRAM_BOT_TOKEN")
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"missing env var: {token_env}")

    raw_ids = cfg.get("approver_chat_ids", [])
    if not raw_ids:
        raise RuntimeError(
            "bridge.approver_chat_ids is empty — Ubik has nobody to whisper to"
        )
    chat_ids = [int(x) for x in raw_ids]

    parse_mode = cfg.get("parse_mode", "MarkdownV2")
    return TelegramBridge(
        TelegramConfig(bot_token=token, chat_ids=chat_ids, parse_mode=parse_mode)
    )
