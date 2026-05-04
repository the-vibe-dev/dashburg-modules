from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Trend Harvester"
    app_env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./trend_harvester.db"

    youtube_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    ollama_base_urls: str = ""
    ollama_model: str = "qwen3:14b"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_large_model: str = "gpt-5"
    openai_timeout_seconds: float = 90.0
    openai_strategy_enabled: bool = True
    openai_key_file: str = "./data/openai_api_key.json"
    run_logs_dir: str = "./data/run_logs"
    run_logs_default_limit: int = 250

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "trend-harvester/0.1"
    x_trends_base_urls: str = ""
    enable_source_cache: bool = False
    channel_metadata_ttl_days: int = 7
    channel_ranking_min_overlap: int = 1
    channel_ranking_min_relevance_pct: int = 1
    channel_ranking_debug_default: bool = False

    request_timeout_seconds: float = 20.0
    retries: int = 5
    backoff_base_seconds: float = 0.5

    default_run_size: Literal["small", "medium", "large"] = "small"
    small_youtube_limit: int = 40
    small_reddit_limit: int = 40
    small_trends_limit: int = 20
    small_x_limit: int = 20
    medium_youtube_limit: int = 100
    medium_reddit_limit: int = 100
    medium_trends_limit: int = 50
    medium_x_limit: int = 50
    large_youtube_limit: int = 200
    large_reddit_limit: int = 200
    large_trends_limit: int = 100
    large_x_limit: int = 100

    max_youtube_limit: int = 200
    max_reddit_limit: int = 200
    max_trends_limit: int = 100
    max_x_limit: int = 100

    llm_cache_days: int = 7
    llm_max_parallel: int = 3
    llm_num_predict: int = 180
    llm_analyze_num_predict: int = 950
    llm_analyze_num_ctx: int = 4096
    llm_analyze_temperature: float = 0.15
    llm_timeout_seconds: float = 120.0
    llm_max_http_attempts_per_run: int = 600
    redis_broker_enabled: bool = True
    redis_broker_base_url: str = "http://127.0.0.1:8710"
    redis_llm_jobs_path: str = "/llm/jobs"
    redis_broker_poll_s: float = 1.0
    redis_broker_timeout_s: float = 900.0
    similarity_threshold: float = 88.0
    novelty_repeat_penalty: float = 4.0
    novelty_skip_penalty: float = 20.0
    novelty_used_penalty: float = 30.0
    novelty_blacklist_penalty: float = 100.0

    @field_validator("ollama_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
