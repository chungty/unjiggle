from __future__ import annotations

import webbrowser

from unjiggle import render


class StubConsole:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message: str) -> None:
        self.messages.append(message)


def test_render_to_png_returns_false_without_browser(tmp_path, monkeypatch):
    html_path = tmp_path / "card.html"
    png_path = tmp_path / "card.png"
    html_path.write_text("<html></html>")

    monkeypatch.setattr(render, "_find_chrome", lambda: None)

    assert render.render_to_png(html_path, png_path) is False


def test_render_to_png_invokes_chrome_with_expected_flags(tmp_path, monkeypatch):
    html_path = tmp_path / "card.html"
    png_path = tmp_path / "card.png"
    html_path.write_text("<html></html>")

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        png_path.write_bytes(b"png")
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 30

    monkeypatch.setattr(render, "_find_chrome", lambda: "/Applications/Test Chrome")
    monkeypatch.setattr(render.subprocess, "run", fake_run)

    assert render.render_to_png(html_path, png_path) is True
    assert calls == [[
        "/Applications/Test Chrome",
        "--headless=new",
        f"--screenshot={png_path.resolve()}",
        f"--window-size={render.CARD_WIDTH},{render.CARD_HEIGHT}",
        "--hide-scrollbars",
        "--disable-gpu",
        "--no-sandbox",
        f"file://{html_path.resolve()}",
    ]]


def test_copy_text_is_mac_only(monkeypatch):
    monkeypatch.setattr(render.sys, "platform", "linux")
    assert render.copy_text("hello") is False


def test_copy_image_requires_existing_png_on_mac(tmp_path, monkeypatch):
    png_path = tmp_path / "card.png"
    monkeypatch.setattr(render.sys, "platform", "darwin")

    assert render.copy_image(png_path) is False


def test_export_card_returns_png_and_reports_clipboard_success(tmp_path, monkeypatch):
    html_path = tmp_path / "card.html"
    png_path = html_path.with_suffix(".png")
    html_path.write_text("<html></html>")
    console = StubConsole()

    monkeypatch.setattr(render, "render_to_png", lambda html, png: png.write_bytes(b"png") or True)
    monkeypatch.setattr(render, "copy_image", lambda path: True)

    result = render.export_card(html_path, console)

    assert result == png_path
    assert any("copied to clipboard" in message for message in console.messages)


def test_export_card_falls_back_to_browser_preview(tmp_path, monkeypatch):
    html_path = tmp_path / "card.html"
    html_path.write_text("<html></html>")
    opened: list[str] = []
    console = StubConsole()

    monkeypatch.setattr(render, "render_to_png", lambda html, png: False)
    monkeypatch.setattr(webbrowser, "open", opened.append)

    result = render.export_card(html_path, console)

    assert result is None
    assert opened == [f"file://{html_path.resolve()}"]
    assert any("opened in browser" in message for message in console.messages)
