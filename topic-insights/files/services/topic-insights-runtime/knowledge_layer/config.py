from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


@dataclass(frozen=True)
class KnowledgeConfig:
    enabled: bool = True
    api_url: str = "http://127.0.0.1:8090"
    api_token: str = ""
    timeout_seconds: float = 5.0
    read_enabled: bool = True
    write_enabled: bool = True
    mail_read_enabled: bool = True
    mail_write_enabled: bool = True
    mail_redaction_enabled: bool = True
    min_confidence: float = 0.70
    min_usefulness: float = 0.70
    fail_hard: bool = False
    spool_enabled: bool = True
    spool_dir: str = ""
    spool_file_name: str = "knowledge_spool.jsonl"

    @classmethod
    def from_env(cls, *, spool_dir: str | None = None) -> "KnowledgeConfig":
        selected_spool_dir = spool_dir or os.getenv("KNOWLEDGE_SPOOL_DIR", "").strip()
        if not selected_spool_dir:
            selected_spool_dir = str((Path.cwd() / "data" / "knowledge").resolve())
        return cls(
            enabled=_bool_env("KNOWLEDGE_API_ENABLED", True),
            api_url=os.getenv("KNOWLEDGE_API_URL", "http://127.0.0.1:8090").strip().rstrip("/"),
            api_token=os.getenv("KNOWLEDGE_API_TOKEN", "").strip(),
            timeout_seconds=_float_env("KNOWLEDGE_API_TIMEOUT_SECONDS", 5.0),
            read_enabled=_bool_env("KNOWLEDGE_READ_ENABLED", True),
            write_enabled=_bool_env("KNOWLEDGE_WRITE_ENABLED", True),
            mail_read_enabled=_bool_env("KNOWLEDGE_MAIL_READ_ENABLED", True),
            mail_write_enabled=_bool_env("KNOWLEDGE_MAIL_WRITE_ENABLED", True),
            mail_redaction_enabled=_bool_env("KNOWLEDGE_MAIL_REDACTION_ENABLED", True),
            min_confidence=_float_env("KNOWLEDGE_MIN_CONFIDENCE", 0.70),
            min_usefulness=_float_env("KNOWLEDGE_MIN_USEFULNESS", 0.70),
            fail_hard=_bool_env("KNOWLEDGE_FAIL_HARD", False),
            spool_enabled=_bool_env("KNOWLEDGE_SPOOL_ENABLED", True),
            spool_dir=selected_spool_dir,
            spool_file_name=os.getenv("KNOWLEDGE_SPOOL_FILE_NAME", "knowledge_spool.jsonl").strip() or "knowledge_spool.jsonl",
        )

    @property
    def spool_path(self) -> Path:
        root = Path(self.spool_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root / self.spool_file_name
