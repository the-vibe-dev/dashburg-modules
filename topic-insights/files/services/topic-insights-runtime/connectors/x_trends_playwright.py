from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from core.config import settings

log = logging.getLogger(__name__)

_POST_COUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMB])?\s+posts?\b", re.IGNORECASE)


@dataclass(frozen=True)
class XTrendsOptions:
    enabled: bool = False
    max_items: int = 20
    timeout_ms: int = 10_000
    nav_timeout_ms: int = 15_000
    use_auth: bool = False
    storage_state_path: str = "./secrets/x_storage_state.json"
    locale: str = "en-US"
    region_hint: str = "US"
    primary_url: str = "https://x.com/explore/tabs/trending"
    fallback_url: str = "https://x.com/explore"
    debug: bool = False


def normalize_trend_topic(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"(^|\s)#", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_post_count_value(post_count_text: str | None) -> float | None:
    if not post_count_text:
        return None
    m = _POST_COUNT_RE.search(post_count_text)
    if not m:
        return None
    base = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    multiplier = 1.0
    if suffix == "K":
        multiplier = 1_000.0
    elif suffix == "M":
        multiplier = 1_000_000.0
    elif suffix == "B":
        multiplier = 1_000_000_000.0
    return base * multiplier


def parse_trend_text_block(text_block: str) -> dict[str, str | None]:
    lines = [ln.strip() for ln in str(text_block or "").splitlines() if ln and ln.strip()]
    if not lines:
        return {"category": None, "title": None, "post_count_text": None}

    post_count_text: str | None = None
    for ln in reversed(lines):
        if _POST_COUNT_RE.search(ln):
            post_count_text = ln
            break

    title: str | None = None
    for ln in lines:
        if ln == post_count_text:
            continue
        if re.search(r"(?i)\b(trending|news|sports|entertainment|for you)\b", ln):
            continue
        title = ln
        break
    if title is None:
        title = lines[0]

    category: str | None = None
    if lines:
        first = lines[0]
        if first != title and first != post_count_text:
            category = first
        elif len(lines) > 1 and lines[1] != title and lines[1] != post_count_text:
            category = lines[1]

    return {"category": category, "title": title, "post_count_text": post_count_text}


def _build_source_id(title: str) -> str:
    canonical = normalize_trend_topic(title)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]
    return f"xtrend:{digest}"


def _build_search_url(title: str, fallback_url: str) -> str:
    clean = str(title or "").strip()
    if not clean:
        return fallback_url
    return f"https://x.com/search?q={quote_plus(clean)}&src=trend_click&f=live"


def _resolve_options(options: dict[str, Any] | None = None) -> XTrendsOptions:
    raw = options or {}
    max_items = int(raw.get("max_items", settings.x_trends_max_items))
    max_items = max(1, min(30, max_items))
    return XTrendsOptions(
        enabled=bool(raw.get("enabled", settings.enable_x_trends)),
        max_items=max_items,
        timeout_ms=max(1_000, int(raw.get("timeout_ms", settings.x_trends_timeout_ms))),
        nav_timeout_ms=max(1_000, int(raw.get("nav_timeout_ms", settings.x_trends_nav_timeout_ms))),
        use_auth=bool(raw.get("use_auth", settings.x_trends_use_auth)),
        storage_state_path=str(raw.get("storage_state_path", settings.x_trends_storage_state_path)),
        locale=str(raw.get("locale", settings.x_trends_locale)),
        region_hint=str(raw.get("region_hint", settings.x_trends_region_hint)),
        primary_url=str(raw.get("url", settings.x_trends_url)),
        fallback_url=str(raw.get("fallback_url", settings.x_trends_fallback_url)),
        debug=bool(raw.get("debug", settings.x_trends_debug)),
    )


def _save_debug_snapshot(page: Any, content: str) -> None:
    if not settings.x_trends_debug:
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(settings.data_dir) / "tmp" / "debug" / "x_trends"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"x_trends_{ts}.html"
    html_path.write_text(content, encoding="utf-8")
    try:
        page.screenshot(path=str(out_dir / f"x_trends_{ts}.png"), full_page=True)
    except Exception:
        pass


def _extract_from_page(page: Any, fallback_url: str, max_items: int) -> tuple[list[dict[str, Any]], str | None]:
    js = """
    () => {
      const seen = new Set();
      const out = [];
      const anchors = Array.from(document.querySelectorAll('a[href*="/search?q="], a[href*="/hashtag/"]'));
      for (const a of anchors) {
        const txt = (a.textContent || '').trim();
        if (!txt) continue;
        const href = a.getAttribute('href') || '';
        const card = a.closest('article,[data-testid="cellInnerDiv"],section,div');
        const block = (card && card.innerText ? card.innerText : txt).trim();
        const key = (txt + '|' + block).toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({
          label: txt,
          href: href,
          text_block: block,
        });
        if (out.length >= 120) break;
      }
      return out;
    }
    """
    rows = page.evaluate(js) or []
    if not isinstance(rows, list):
        rows = []

    trends: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        label = str((row or {}).get("label") or "").strip()
        text_block = str((row or {}).get("text_block") or "").strip()
        href = str((row or {}).get("href") or "").strip()
        parsed = parse_trend_text_block(text_block)
        title = str(parsed.get("title") or label).strip()
        if not title:
            continue
        if normalize_trend_topic(title) in {"trending", "for you", "news", "sports", "entertainment"}:
            continue
        url = fallback_url
        if href.startswith("http://") or href.startswith("https://"):
            url = href
        elif href.startswith("/"):
            url = f"https://x.com{href}"
        else:
            url = _build_search_url(title, fallback_url)
        rank = len(trends) + 1
        trends.append(
            {
                "source": "x",
                "source_id": _build_source_id(title),
                "title": title,
                "url": url,
                "published_at": None,
                "metrics": {
                    "rank": rank,
                    "post_count_text": parsed.get("post_count_text"),
                    "category": parsed.get("category"),
                    "tab_label": None,
                },
                "source_confidence": "medium" if parsed.get("title") else "low",
                "raw_json": {
                    "label": label,
                    "text_block": text_block,
                    "href": href,
                    "parsed": parsed,
                },
            }
        )
        if len(trends) >= max_items:
            break

    warning = None
    if not trends:
        warning = "No trend cards parsed from x.com; extraction returned empty."
    return trends[:max_items], warning


def fetch_x_trends(options: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    opts = _resolve_options(options)
    warnings: list[str] = []
    if not opts.enabled:
        return [], warnings

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        warnings.append(f"Playwright not available: {exc}")
        return [], warnings

    urls = [opts.primary_url, opts.fallback_url]
    trends: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, timeout=opts.nav_timeout_ms)
        context = None
        page = None
        try:
            context_kwargs: dict[str, Any] = {
                "locale": opts.locale,
                "user_agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
            }
            storage_path = Path(opts.storage_state_path)
            if opts.use_auth:
                if storage_path.exists():
                    context_kwargs["storage_state"] = str(storage_path)
                else:
                    warnings.append("X auth storage state file missing; continuing unauthenticated.")
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.set_default_timeout(opts.timeout_ms)
            page.set_default_navigation_timeout(opts.nav_timeout_ms)

            for attempt, url in enumerate(urls[:2]):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=opts.nav_timeout_ms)
                    page.wait_for_timeout(800)
                    page.wait_for_selector("a[href*='/search?q='], a[href*='/hashtag/']", timeout=opts.timeout_ms)
                except PlaywrightTimeoutError:
                    warnings.append(f"Timed out waiting for trend cards on {url}; fallback extraction used.")
                except Exception as exc:
                    warnings.append(f"X page navigation issue on {url}: {exc}")

                html = page.content()
                if opts.debug:
                    _save_debug_snapshot(page, html)

                extracted, warning = _extract_from_page(page, opts.fallback_url, opts.max_items)
                if warning:
                    warnings.append(warning)
                if extracted:
                    trends = extracted
                    break
                if attempt == 0:
                    page.wait_for_timeout(500)
        except Exception as exc:
            warnings.append(f"X trends scrape failed: {exc}")
        finally:
            try:
                if page is not None:
                    page.close()
            except Exception:
                pass
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    # Final uniqueness pass by normalized title.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in trends:
        key = normalize_trend_topic(str(item.get("title") or ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= opts.max_items:
            break

    if warnings:
        log.warning("x_trends_warnings count=%s warnings=%s", len(warnings), json.dumps(warnings)[:1200])
    return deduped, warnings

