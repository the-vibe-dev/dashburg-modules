from __future__ import annotations
from datetime import datetime
import hashlib
import logging
from bs4 import BeautifulSoup
from ingestion.common.http import get
from ingestion.web.router import search as router_search
from core.http_client import run_async
from storage.models import RawPost

def web_search(query: str, limit: int = 20) -> list[RawPost]:
    out: list[RawPost] = []
    log = logging.getLogger(__name__)
    log.info("web_search query=%s limit=%s", query, limit)
    results = run_async(router_search(query=query, limit=limit))
    if not results:
        log.warning("web_search_no_results")
    for r in results:
        url = r.url
        title = r.title
        snippet = r.snippet
        # best-effort fetch to pull some page text; failure should not kill the scan
        page_text = ""
        try:
            resp = get(url, timeout=15.0, headers={"Accept": "text/html,*/*;q=0.8"}, limiter_name="web")
            soup = BeautifulSoup(resp.text, "lxml")
            # remove script/style
            for tag in soup(["script", "style", "noscript"]):
                tag.extract()
            page_text = " ".join(soup.get_text(" ").split())
            page_text = page_text[:8000]
        except Exception:
            page_text = ""
        combined = (title + "\n\n" + snippet + ("\n\n" + page_text if page_text else "")).strip()
        hid = hashlib.sha1((url + title).encode()).hexdigest()
        out.append(
            RawPost(
            id=f"web:{hid}",
            source="web",
            url=url,
            author=None,
            timestamp=datetime.utcnow(),
            text=combined[:20000],
            engagement_score=0,
            metadata_={"title": title},
        )
        )
    log.info("web_search_done count=%s", len(out))
    return out
