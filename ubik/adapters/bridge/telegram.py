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

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .base import ApprovalEvent, Bridge, Decision, NotifyMessage, ProposalMessage, Severity

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
        await self._send_to_all(text=text)

    async def propose(self, message: ProposalMessage) -> dict[str, str]:
        """Push a proposal with ✅ / 👁 / ❌ inline buttons.

        Telegram callback_data fires back at our long-poll loop with the
        proposal id + decision verb encoded as ``ubik:<verb>:<id>``.
        """
        nm = NotifyMessage(
            title=message.title,
            body_markdown=message.body_markdown,
            footer=message.footer,
            severity=message.severity,
            tags=message.tags,
        )
        text = self._render(nm)

        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Apply",   "callback_data": f"ubik:approve:{message.proposal_id}"},
                {"text": "👁 Diff",    "callback_data": f"ubik:diff:{message.proposal_id}"},
                {"text": "❌ Reject",  "callback_data": f"ubik:reject:{message.proposal_id}"},
            ]]
        }

        # Send to the FIRST chat only — proposals are routed to the
        # primary approver. Notify (broadcast) keeps the multi-chat
        # behaviour. Returns the message refs we'll need to edit later.
        primary = self.config.chat_ids[0]
        refs: dict[str, str] = {}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self._endpoint}/sendMessage",
                json={
                    "chat_id": primary,
                    "text": text,
                    "parse_mode": self.config.parse_mode,
                    "disable_web_page_preview": True,
                    "reply_markup": keyboard,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "Telegram propose send failed (chat=%s, status=%d): %s",
                    primary, resp.status_code, resp.text[:300],
                )
                return refs
            data = resp.json()
            result = data.get("result", {})
            refs = {
                "chat_id": str(primary),
                "message_id": str(result.get("message_id", "")),
            }
            logger.info("Telegram proposal sent → chat=%s msg=%s",
                        primary, refs.get("message_id"))
        return refs

    async def edit_message(
        self,
        chat_id: str | int,
        message_id: str | int,
        new_text: str,
        *,
        keep_keyboard: bool = False,
    ) -> bool:
        """Replace a previously-sent message's body. Used to lock proposals
        once the user has acted (so they can't tap twice)."""
        async with httpx.AsyncClient(timeout=15) as client:
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "message_id": int(message_id),
                "text": new_text,
                "parse_mode": self.config.parse_mode,
                "disable_web_page_preview": True,
            }
            if not keep_keyboard:
                payload["reply_markup"] = {"inline_keyboard": []}
            resp = await client.post(f"{self._endpoint}/editMessageText", json=payload)
            return resp.status_code == 200

    async def _send_to_all(self, *, text: str) -> None:
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
                        logger.warning(
                            "Telegram send failed (chat=%s, status=%d): %s",
                            chat_id, resp.status_code, resp.text[:200],
                        )
                    else:
                        logger.info("Telegram notify sent → chat=%s", chat_id)
                except httpx.HTTPError as e:
                    logger.warning("Telegram notify network error (chat=%s): %s", chat_id, e)

    # ── inbound: long-poll callbacks ─────────────────────────────────────

    async def poll_approvals(
        self,
        *,
        on_event,
        offset_state_path: Path | None = Path.home() / ".ubik" / "poll-offset",
        timeout: int = 25,
    ) -> None:
        """Long-poll Telegram for callback_query events forever.

        ``on_event`` is awaited with each ApprovalEvent. ``offset_state_path``
        is a small file we use to remember the last update_id between
        restarts (so we don't reprocess the same tap twice).

        Run this from the orchestrator main loop. On any HTTP error we
        backoff then retry — keeps running across transient outages.
        """
        if offset_state_path:
            offset_state_path.parent.mkdir(parents=True, exist_ok=True)

        last_update_id: int = 0
        if offset_state_path and offset_state_path.exists():
            try:
                last_update_id = int(offset_state_path.read_text().strip() or 0)
            except ValueError:
                last_update_id = 0

        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{self._endpoint}/getUpdates",
                        params={
                            "offset": last_update_id + 1,
                            "timeout": timeout,
                            "allowed_updates": ["callback_query"],
                        },
                    )
                except httpx.HTTPError as e:
                    logger.warning("getUpdates error: %s — sleeping 5s", e)
                    await asyncio.sleep(5)
                    continue

                if resp.status_code != 200:
                    logger.warning("getUpdates status=%d body=%s",
                                   resp.status_code, resp.text[:200])
                    await asyncio.sleep(5)
                    continue

                data = resp.json()
                for update in data.get("result", []):
                    last_update_id = max(last_update_id, update.get("update_id", 0))
                    cb = update.get("callback_query")
                    if not cb:
                        continue

                    event = self._parse_callback(cb)
                    if not event:
                        continue

                    # Acknowledge the tap so the spinner stops.
                    cb_id = cb.get("id")
                    if cb_id:
                        try:
                            await client.post(
                                f"{self._endpoint}/answerCallbackQuery",
                                json={"callback_query_id": cb_id},
                            )
                        except httpx.HTTPError:
                            pass

                    try:
                        await on_event(event)
                    except Exception as e:
                        logger.error("Approval handler raised: %s", e, exc_info=True)

                if offset_state_path:
                    offset_state_path.write_text(str(last_update_id))

    def _parse_callback(self, cb: dict[str, Any]) -> ApprovalEvent | None:
        """Map a Telegram callback_query to an ApprovalEvent. Ignore strangers."""
        from datetime import datetime, timezone

        cb_data = cb.get("data", "")
        if not cb_data.startswith("ubik:"):
            return None

        try:
            _, verb, proposal_id = cb_data.split(":", 2)
        except ValueError:
            return None

        # Auth gate — only configured approver chat_ids can act.
        from_user = cb.get("from", {})
        msg = cb.get("message", {})
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        if chat_id not in self.config.chat_ids:
            logger.warning("Ignored callback from unauthorized chat=%s", chat_id)
            return None

        verb_to_decision = {
            "approve": Decision.APPROVED,
            "reject": Decision.REJECTED,
            "diff": Decision.PENDING,    # 'diff' means 'show me more'; not a final decision
            "refine": Decision.REFINE,
        }
        decision = verb_to_decision.get(verb)
        if not decision:
            return None

        return ApprovalEvent(
            proposal_id=proposal_id,
            decision=decision,
            by=str(from_user.get("username") or from_user.get("id") or ""),
            at=datetime.now(timezone.utc).isoformat(),
        )

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
    """Build a TelegramBridge from the `bridge` block of ubik.yaml.

    Chat-id resolution: the YAML's ``approver_chat_ids`` list wins. If
    empty, fall back to the env var named by ``chat_id_env`` (default
    ``TELEGRAM_CHAT_ID``) — comma-separated int(s).
    """
    token_env = cfg.get("token_env", "TELEGRAM_BOT_TOKEN")
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"missing env var: {token_env}")

    chat_ids = [int(x) for x in (cfg.get("approver_chat_ids") or [])]
    if not chat_ids:
        chat_id_env = cfg.get("chat_id_env", "TELEGRAM_CHAT_ID")
        raw = os.environ.get(chat_id_env, "").strip()
        if raw:
            chat_ids = [int(x.strip()) for x in raw.split(",") if x.strip()]

    if not chat_ids:
        raise RuntimeError(
            "bridge.approver_chat_ids is empty and no fallback in "
            f"{cfg.get('chat_id_env', 'TELEGRAM_CHAT_ID')!r} — "
            "Ubik has nobody to whisper to"
        )

    parse_mode = cfg.get("parse_mode", "MarkdownV2")
    return TelegramBridge(
        TelegramConfig(bot_token=token, chat_ids=chat_ids, parse_mode=parse_mode)
    )
