from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from trend_harvester.config import get_settings


def _key_path() -> Path:
    settings = get_settings()
    path = Path(settings.openai_key_file).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


def _read_file_key() -> str:
    path = _key_path()
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return str(payload.get("api_key", "")).strip()
    except Exception:
        return ""


def get_openai_api_key() -> str:
    env_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
    if env_key:
        return env_key
    return _read_file_key()


def openai_api_key_status() -> dict[str, Any]:
    env_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
    if env_key:
        return {"configured": True, "source": "env", "masked": _mask(env_key)}
    file_key = _read_file_key()
    if file_key:
        return {"configured": True, "source": "file", "masked": _mask(file_key)}
    return {"configured": False, "source": "none", "masked": ""}


def set_openai_api_key(api_key: str) -> dict[str, Any]:
    key = str(api_key).strip()
    if not key:
        raise ValueError("api_key is required")
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"api_key": key}, ensure_ascii=True), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return openai_api_key_status()


def clear_openai_api_key() -> dict[str, Any]:
    path = _key_path()
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    return openai_api_key_status()
