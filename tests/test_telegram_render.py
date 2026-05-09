"""Tests for the Telegram MarkdownLite → HTML rendering."""
from __future__ import annotations

from ubik.adapters.bridge.telegram import (
    TelegramBridge,
    TelegramConfig,
    _escape_html,
    _escape_md_v2,
    _markdown_lite_to_html,
)
from ubik.adapters.bridge.base import NotifyMessage, Severity


def test_escape_html_handles_three_reserved_chars() -> None:
    assert _escape_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"
    # Idempotent on plain text.
    assert _escape_html("hello world") == "hello world"


def test_escape_md_v2_escapes_reserved() -> None:
    assert _escape_md_v2("hello!") == "hello\\!"
    assert _escape_md_v2("a-b.c") == "a\\-b\\.c"


def test_markdown_lite_bold() -> None:
    assert _markdown_lite_to_html("**foo**") == "<b>foo</b>"
    assert _markdown_lite_to_html("a **b** c") == "a <b>b</b> c"


def test_markdown_lite_italic() -> None:
    out = _markdown_lite_to_html("*emphasis*")
    assert out == "<i>emphasis</i>"
    # Bold should not be misinterpreted as italic.
    assert _markdown_lite_to_html("**bold**") == "<b>bold</b>"


def test_markdown_lite_inline_code() -> None:
    assert _markdown_lite_to_html("`code`") == "<code>code</code>"


def test_markdown_lite_link() -> None:
    out = _markdown_lite_to_html("[full report](https://psssst.dev/x)")
    assert out == '<a href="https://psssst.dev/x">full report</a>'


def test_markdown_lite_escapes_unrelated_html() -> None:
    out = _markdown_lite_to_html("<script>alert('xss')</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_lite_escapes_inside_code_too() -> None:
    out = _markdown_lite_to_html("`<b>not bold</b>`")
    assert out == "<code>&lt;b&gt;not bold&lt;/b&gt;</code>"


def test_markdown_lite_handles_dashes_and_dots_unescaped() -> None:
    # The whole bug we were fixing — '-' and '.' must NOT need escaping
    # in the HTML path. They're plain characters there.
    out = _markdown_lite_to_html("- one.\n- two.\n- three!")
    assert "-" in out and "." in out and "!" in out
    # Should not contain backslashes.
    assert "\\" not in out


def test_render_html_full_message() -> None:
    bridge = TelegramBridge(
        TelegramConfig(bot_token="x", chat_ids=[1], parse_mode="HTML")
    )
    msg = NotifyMessage(
        title="Pssst! Audit · ubik",
        body_markdown="**3 findings** · 1 critical\n\n- Foo & bar\n- Baz",
        footer="ubik audit",
        severity=Severity.HIGH,
    )
    text = bridge._render(msg)
    # Title bolded, severity icon prepended.
    assert "<b>Pssst! Audit · ubik</b>" in text
    assert text.startswith("⚠️")
    # Body's bold survived.
    assert "<b>3 findings</b>" in text
    # Stray ampersand escaped.
    assert "Foo &amp; bar" in text
    # Footer italicized.
    assert "<i>ubik audit</i>" in text


def test_render_truncates_at_max_chars() -> None:
    bridge = TelegramBridge(
        TelegramConfig(
            bot_token="x", chat_ids=[1], parse_mode="HTML", max_message_chars=200
        )
    )
    msg = NotifyMessage(title="t", body_markdown="x" * 1000)
    text = bridge._render(msg)
    assert len(text) <= 200
    assert "(truncated)" in text
