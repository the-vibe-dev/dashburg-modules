from __future__ import annotations
import logging
from core.logging import setup_logging
from extraction.pain_extractor import extract_pains_from_posts, PROMPT_PATH
from storage.models import RawPost, ExtractedPain
from storage.repository import insert_pains
from core.config import settings

def extract_pains(raw_posts: list[RawPost], topic: str, run_id: str | None = None) -> list[ExtractedPain]:
    setup_logging(logging.DEBUG if settings.verbose else logging.INFO)
    log = logging.getLogger(__name__)
    pains = extract_pains_from_posts(raw_posts, topic=topic, run_id=run_id)
    if not pains and raw_posts:
        provider = "openai" if settings.llm_provider == "openai" else "ollama"
        model = settings.openai_model_primary if settings.llm_provider == "openai" else settings.ollama_model
        sample_texts = [p.text[:200] for p in raw_posts[:3]]
        log.warning(
            "extract_zero_pains posts=%s provider=%s model=%s prompt=%s sample_texts=%s",
            len(raw_posts),
            provider,
            model,
            str(PROMPT_PATH),
            sample_texts,
        )
    insert_pains(pains)
    return pains
