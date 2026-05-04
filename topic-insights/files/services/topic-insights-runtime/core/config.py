from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = str(BASE_DIR / "data")
DEFAULT_DB_URL = f"sqlite:///{(BASE_DIR / 'data' / 'oie.db')}"

def _normalize_data_dir(value: str) -> str:
    p = Path(value)
    if not p.is_absolute():
        return str((BASE_DIR / p).resolve())
    return str(p)

def _normalize_db_url(url: str) -> str:
    if url.startswith("sqlite:///") and "/./" in url:
        path = url.replace("sqlite:///", "")
        p = Path(path)
        if not p.is_absolute():
            return f"sqlite:///{(BASE_DIR / p).resolve()}"
    return url

@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("OIE_ENV", "local")
    database_url: str = _normalize_db_url(os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    data_dir: str = _normalize_data_dir(os.getenv("DATA_DIR", DEFAULT_DATA_DIR))
    verbose: bool = os.getenv("OIE_VERBOSE", "false").lower() in ("1", "true", "yes")

    # OpenAI
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_embed_model: str = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    # Ollama
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_chat_model: str = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:14b-instruct")
    ollama_embed_model: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    # Ingestion
    reddit_user_agent: str = os.getenv("REDDIT_USER_AGENT", "OIE/1.0")
    default_rate_limit_sleep: float = float(os.getenv("DEFAULT_RATE_LIMIT_SLEEP", "1.0"))

    # Web search
    web_search_enabled: bool = os.getenv("WEB_SEARCH_ENABLED", "true").lower() in ("1", "true", "yes")
    web_search_provider: str = os.getenv("WEB_SEARCH_PROVIDER", "auto")
    web_search_fallbacks: str = os.getenv("WEB_SEARCH_FALLBACKS", "ddg,serpapi,dataforseo,none")
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "50"))
    web_search_retries: int = int(os.getenv("WEB_SEARCH_RETRIES", "4"))
    web_search_backoff_base: float = float(os.getenv("WEB_SEARCH_BACKOFF_BASE", "1.0"))
    web_search_cooldown_seconds: int = int(os.getenv("WEB_SEARCH_COOLDOWN_SECONDS", "60"))
    web_search_cache_ttl_seconds: int = int(os.getenv("WEB_SEARCH_CACHE_TTL_SECONDS", "86400"))
    web_search_timeout_seconds: float = float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS", "20"))
    web_search_max_wait_total: float = float(os.getenv("WEB_SEARCH_MAX_WAIT_TOTAL", "45"))
    serpapi_api_key: str | None = os.getenv("SERPAPI_API_KEY")
    dataforseo_login: str | None = os.getenv("DATAFORSEO_LOGIN")
    dataforseo_password: str | None = os.getenv("DATAFORSEO_PASSWORD")

    # LLM routing
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama")
    llm_fallback_provider: str = os.getenv("LLM_FALLBACK_PROVIDER", "openai")
    llm_cache_ttl_seconds: int = int(os.getenv("LLM_CACHE_TTL_SECONDS", "604800"))
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
    llm_batch_size: int = int(os.getenv("LLM_BATCH_SIZE", "10"))
    llm_max_calls_per_run: int = int(os.getenv("LLM_MAX_CALLS_PER_RUN", "40"))
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:14b")
    openai_model_primary: str = os.getenv("OPENAI_MODEL_PRIMARY", "gpt-4o-mini")
    openai_model_eval: str = os.getenv("OPENAI_MODEL_EVAL", "gpt-4o-mini")

    # Prompt sizing / context budgets
    llm_max_input_chars: int = int(os.getenv("LLM_MAX_INPUT_CHARS", "24000"))
    llm_max_examples: int = int(os.getenv("LLM_MAX_EXAMPLES", "40"))
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
    ollama_num_predict: int = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))
    ollama_temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))

    # Concurrency limits
    web_max_concurrency: int = int(os.getenv("WEB_MAX_CONCURRENCY", "4"))
    reddit_max_concurrency: int = int(os.getenv("REDDIT_MAX_CONCURRENCY", "4"))
    youtube_max_concurrency: int = int(os.getenv("YOUTUBE_MAX_CONCURRENCY", "2"))
    llm_local_max_concurrency: int = int(os.getenv("LLM_LOCAL_MAX_CONCURRENCY", "2"))
    llm_openai_max_concurrency: int = int(os.getenv("LLM_OPENAI_MAX_CONCURRENCY", "4"))
    redis_broker_enabled: bool = os.getenv("REDIS_BROKER_ENABLED", "1").lower() in ("1", "true", "yes")
    redis_broker_base_url: str = os.getenv("REDIS_BROKER_BASE_URL", "http://192.168.1.177:8710")
    redis_llm_jobs_path: str = os.getenv("REDIS_LLM_JOBS_PATH", "/llm/jobs")
    redis_broker_poll_s: float = float(os.getenv("REDIS_BROKER_POLL_S", "1.0"))
    redis_broker_timeout_s: float = float(os.getenv("REDIS_BROKER_TIMEOUT_S", "900"))

    reddit_max_posts: int = int(os.getenv("REDDIT_MAX_POSTS", "50"))
    reddit_max_comment_posts: int = int(os.getenv("REDDIT_MAX_COMMENT_POSTS", "10"))
    reddit_max_comments_per_post: int = int(os.getenv("REDDIT_MAX_COMMENTS_PER_POST", "120"))

    enable_youtube: bool = os.getenv("ENABLE_YOUTUBE", "false").lower() in ("1", "true", "yes")
    youtube_region: str = os.getenv("YOUTUBE_REGION", "US")
    youtube_api_key: str | None = os.getenv("YOUTUBE_API_KEY")
    youtube_max_videos: int = int(os.getenv("YOUTUBE_MAX_VIDEOS", "10"))
    youtube_max_comments_per_video: int = int(os.getenv("YOUTUBE_MAX_COMMENTS_PER_VIDEO", "50"))
    youtube_search_max_results: int = int(os.getenv("YOUTUBE_SEARCH_MAX_RESULTS", "50"))

    # X trends (optional Playwright connector)
    enable_x_trends: bool = os.getenv("ENABLE_X_TRENDS", "false").lower() in ("1", "true", "yes")
    x_trends_url: str = os.getenv("X_TRENDS_URL", "https://x.com/explore/tabs/trending")
    x_trends_fallback_url: str = os.getenv("X_TRENDS_FALLBACK_URL", "https://x.com/explore")
    x_trends_max_items: int = int(os.getenv("X_TRENDS_MAX_ITEMS", "20"))
    x_trends_timeout_ms: int = int(os.getenv("X_TRENDS_TIMEOUT_MS", "10000"))
    x_trends_nav_timeout_ms: int = int(os.getenv("X_TRENDS_NAV_TIMEOUT_MS", "15000"))
    x_trends_use_auth: bool = os.getenv("X_TRENDS_USE_AUTH", "false").lower() in ("1", "true", "yes")
    x_trends_storage_state_path: str = os.getenv("X_TRENDS_STORAGE_STATE_PATH", "./secrets/x_storage_state.json")
    x_trends_locale: str = os.getenv("X_TRENDS_LOCALE", "en-US")
    x_trends_region_hint: str = os.getenv("X_TRENDS_REGION_HINT", "US")
    x_trends_debug: bool = os.getenv("X_TRENDS_DEBUG", "false").lower() in ("1", "true", "yes")

    competition_scan_enabled: bool = os.getenv("COMPETITION_SCAN_ENABLED", "true").lower() in ("1","true","yes")
    competition_scan_results: int = int(os.getenv("COMPETITION_SCAN_RESULTS", "10"))

    auto_discovery_enabled: bool = os.getenv("AUTO_DISCOVERY_ENABLED", "true").lower() in ("1","true","yes")
    auto_discovery_target_topics: int = int(os.getenv("AUTO_DISCOVERY_TARGET_TOPICS", "20"))
    auto_discovery_ideas_per_run: int = int(os.getenv("AUTO_DISCOVERY_IDEAS_PER_RUN", "5"))
    auto_discovery_limit_per_topic: int = int(os.getenv("AUTO_DISCOVERY_LIMIT_PER_TOPIC", "30"))

    google_trends_geo: str = os.getenv("GOOGLE_TRENDS_GEO", "US")
    google_trends_timeframe: str = os.getenv("GOOGLE_TRENDS_TIMEFRAME", "today 12-m")

    appstore_scan_enabled: bool = os.getenv("APPSTORE_SCAN_ENABLED", "true").lower() in ("1","true","yes")
    appstore_max_apps: int = int(os.getenv("APPSTORE_MAX_APPS", "6"))
    appstore_max_reviews: int = int(os.getenv("APPSTORE_MAX_REVIEWS", "80"))

settings = Settings()
