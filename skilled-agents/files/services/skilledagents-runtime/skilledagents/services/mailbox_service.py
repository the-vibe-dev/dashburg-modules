from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from skilledagents.services.agent_manager import AgentManager


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MailboxService:
    def __init__(self, manager: AgentManager) -> None:
        self.manager = manager

    def _workspace(self, agent: dict) -> Path:
        return Path(agent["workspace_path"]).resolve()

    def _mailbox_root(self, agent: dict) -> Path:
        return self._workspace(agent) / "mailbox"

    def ensure_mailbox(self, agent: dict) -> Path:
        root = self._mailbox_root(agent)
        (root / "inbox").mkdir(parents=True, exist_ok=True)
        (root / "outbox").mkdir(parents=True, exist_ok=True)
        (root / "archive").mkdir(parents=True, exist_ok=True)
        return root

    def _box_path(self, agent: dict, box: str) -> Path:
        root = self.ensure_mailbox(agent)
        if box not in {"inbox", "outbox", "archive"}:
            raise ValueError(f"unknown mailbox box: {box}")
        return root / box

    def _write_message(self, box_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        message_id = str(payload.get("id") or uuid4().hex)
        record = {
            "id": message_id,
            "created_at": payload.get("created_at") or _now(),
            "sender": str(payload.get("sender") or "unknown"),
            "subject": str(payload.get("subject") or ""),
            "body": str(payload.get("body") or ""),
            "metadata": dict(payload.get("metadata") or {}),
        }
        path = box_path / f"{record['created_at'].replace(':', '-')}_{message_id}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return {**record, "path": str(path)}

    def post_inbox(
        self,
        agent: dict,
        *,
        sender: str,
        subject: str,
        body: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._write_message(
            self._box_path(agent, "inbox"),
            {"sender": sender, "subject": subject, "body": body, "metadata": metadata or {}},
        )

    def post_outbox(
        self,
        agent: dict,
        *,
        sender: str,
        subject: str,
        body: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._write_message(
            self._box_path(agent, "outbox"),
            {"sender": sender, "subject": subject, "body": body, "metadata": metadata or {}},
        )

    def list_box(self, agent: dict, box: str, limit: int = 50) -> list[dict[str, Any]]:
        path = self._box_path(agent, box)
        items: list[dict[str, Any]] = []
        for file in sorted(path.glob("*.json"), reverse=True):
            try:
                row = json.loads(file.read_text(encoding="utf-8"))
            except Exception:
                continue
            row["path"] = str(file)
            items.append(row)
            if len(items) >= limit:
                break
        return items

    def ack_inbox_message(self, agent: dict, message_id: str) -> dict[str, Any] | None:
        inbox = self._box_path(agent, "inbox")
        archive = self._box_path(agent, "archive")
        matches = list(inbox.glob(f"*_{message_id}.json"))
        if not matches:
            return None
        src = matches[0]
        dst = archive / src.name
        shutil.move(str(src), str(dst))
        payload = json.loads(dst.read_text(encoding="utf-8"))
        payload["path"] = str(dst)
        return payload
