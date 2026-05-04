from __future__ import annotations

import builtins

from connectors.x_trends_playwright import _extract_from_page, fetch_x_trends


def test_x_connector_returns_warning_when_playwright_unavailable(monkeypatch):
    original_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("playwright unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    rows, warnings = fetch_x_trends({"enabled": True, "max_items": 5})
    assert rows == []
    assert warnings
    assert "Playwright not available" in warnings[0]


def test_extract_fallback_returns_warning_when_selector_yields_no_rows():
    class _Page:
        def evaluate(self, _js):
            return []

    rows, warning = _extract_from_page(_Page(), "https://x.com/explore", max_items=10)
    assert rows == []
    assert isinstance(warning, str) and "extraction returned empty" in warning
