from __future__ import annotations

import json
import subprocess
from pathlib import Path
from textwrap import dedent

from skilledagents.services.log_service import LogService


class WorkspaceService:
    def __init__(self, log_service: LogService) -> None:
        self.log_service = log_service

    def _manifest_path(self, workspace_path: str) -> Path:
        return Path(workspace_path) / "agent.manifest.json"

    def ensure_workspace(self, agent: dict) -> None:
        workspace = Path(agent["workspace_path"])
        workspace.mkdir(parents=True, exist_ok=True)
        mailbox = workspace / "mailbox"
        (mailbox / "inbox").mkdir(parents=True, exist_ok=True)
        (mailbox / "outbox").mkdir(parents=True, exist_ok=True)
        (mailbox / "archive").mkdir(parents=True, exist_ok=True)
        self._write_runtime_context(agent, workspace)
        self._ensure_runtime_scripts(workspace, agent)

    def write_manifest(self, agent: dict) -> Path:
        manifest = {
            "id": agent["id"],
            "name": agent["name"],
            "slug": agent["slug"],
            "agent_type": agent["agent_type"],
            "runtime": agent["runtime"],
            "model": {
                "provider": agent.get("model_provider"),
                "name": agent.get("model_name"),
                "settings": agent.get("model_settings", {}),
            },
            "skills": agent.get("selected_skills", []),
            "template": {
                "template_id": agent.get("template_id"),
                "specialization_mode": agent.get("specialization_mode"),
                "role_identity": agent.get("role_identity"),
                "domain_focus": agent.get("domain_focus"),
                "execution_mode": agent.get("execution_mode"),
                "allowed_tools": agent.get("allowed_tools", []),
                "runtime_policies": agent.get("runtime_policies", {}),
                "saved_prompts": agent.get("saved_prompts", {}),
                "metadata": agent.get("specialization_metadata", {}),
            },
            "sandbox_mode": agent.get("sandbox_mode"),
            "network_access": agent.get("network_access"),
            "flags": agent.get("flags", {}),
            "env_config": agent.get("env_config", {}),
        }
        path = self._manifest_path(agent["workspace_path"])
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return path

    def attach_skills(self, agent: dict, skills: list[dict]) -> None:
        workspace = Path(agent["workspace_path"])
        links_dir = workspace / "skills"
        links_dir.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            link = links_dir / skill["id"]
            target = Path(skill["path"])
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(target)
            except OSError:
                # Fallback to metadata file when symlink is not allowed.
                (links_dir / f"{skill['id']}.path").write_text(str(target), encoding="utf-8")

    def install_requirements(self, agent: dict, run_id: str | None = None) -> tuple[bool, str]:
        workspace = Path(agent["workspace_path"])
        req = workspace / "requirements.txt"
        if not req.exists():
            return True, "requirements.txt not found; skipped"

        cmd = ["python3", "-m", "pip", "install", "-r", str(req)]
        proc = subprocess.run(cmd, cwd=workspace, capture_output=True, text=True)
        self.log_service.append(agent["id"], run_id, "info", f"$ {' '.join(cmd)}")
        if proc.stdout:
            self.log_service.append(agent["id"], run_id, "stdout", proc.stdout[-6000:])
        if proc.stderr:
            self.log_service.append(agent["id"], run_id, "stderr", proc.stderr[-6000:])
        if proc.returncode != 0:
            return False, f"pip install failed ({proc.returncode})"
        return True, "requirements installed"

    def read_manifest(self, agent: dict) -> dict:
        path = self._manifest_path(agent["workspace_path"])
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_runtime_context(self, agent: dict, workspace: Path) -> None:
        memory = str(((agent.get("flags") or {}).get("memory_context") or {}).get("content") or "").strip()
        if memory:
            (workspace / "MEM.md").write_text(memory + "\n", encoding="utf-8")
        system_prompt = str((agent.get("saved_prompts") or {}).get("system") or "").strip()
        if system_prompt:
            (workspace / "PROMPT_SYSTEM.md").write_text(system_prompt + "\n", encoding="utf-8")

    def _ensure_runtime_scripts(self, workspace: Path, agent: dict) -> None:
        loop = workspace / "agent_loop.py"
        if not loop.exists():
            loop.write_text(self._agent_loop_script(), encoding="utf-8")
        run_sh = workspace / "run.sh"
        if not run_sh.exists():
            poll_seconds = int((agent.get("flags") or {}).get("mailbox_poll_seconds") or 8)
            run_sh.write_text(
                dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    cd "$(dirname "$0")"
                    export AGENT_MAILBOX_POLL_SECONDS="${{AGENT_MAILBOX_POLL_SECONDS:-{poll_seconds}}}"
                    exec python3 agent_loop.py
                    """
                ),
                encoding="utf-8",
            )
            run_sh.chmod(0o755)

    def _agent_loop_script(self) -> str:
        return dedent(
            """\
            #!/usr/bin/env python3
            from __future__ import annotations

            import json
            import os
            import shutil
            import subprocess
            import time
            from datetime import datetime, timezone
            from pathlib import Path
            from uuid import uuid4

            ROOT = Path(__file__).resolve().parent
            MAILBOX = ROOT / "mailbox"
            INBOX = MAILBOX / "inbox"
            OUTBOX = MAILBOX / "outbox"
            ARCHIVE = MAILBOX / "archive"
            POLL = max(2, int(os.getenv("AGENT_MAILBOX_POLL_SECONDS", "8")))


            def _now() -> str:
                return datetime.now(timezone.utc).isoformat()


            def _write_outbox(subject: str, body: str, metadata: dict | None = None) -> None:
                payload = {
                    "id": uuid4().hex,
                    "created_at": _now(),
                    "sender": "agent-runtime",
                    "subject": subject,
                    "body": body,
                    "metadata": metadata or {},
                }
                name = f"{payload['created_at'].replace(':', '-')}_{payload['id']}.json"
                (OUTBOX / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


            def _process_message(path: Path) -> None:
                try:
                    msg = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    _write_outbox("Dispatch Parse Error", f"Failed to parse {path.name}: {exc}", {"path": str(path)})
                    shutil.move(str(path), str(ARCHIVE / path.name))
                    return

                message_id = str(msg.get("id") or path.stem)
                subject = str(msg.get("subject") or "Dispatch")
                instruction = str(msg.get("body") or "").strip()
                metadata = dict(msg.get("metadata") or {})
                command = str(metadata.get("command") or "").strip()

                _write_outbox(
                    "Dispatch Started",
                    f"Started: {subject}\\n\\nInstruction:\\n{instruction}",
                    {"message_id": message_id, "status": "started"},
                )

                if command:
                    proc = subprocess.run(
                        ["bash", "-lc", command],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        timeout=900,
                    )
                    output = (proc.stdout or "") + (("\\n" + proc.stderr) if proc.stderr else "")
                    _write_outbox(
                        "Dispatch Result",
                        f"Command: {command}\\nExit: {proc.returncode}\\n\\n{output[-8000:]}",
                        {"message_id": message_id, "status": "completed", "exit_code": proc.returncode},
                    )
                else:
                    note = (
                        "No command metadata was provided.\\n"
                        "This worker accepted the task and queued it for prompt-driven/manual execution.\\n\\n"
                        f"Instruction:\\n{instruction}"
                    )
                    _write_outbox(
                        "Dispatch Accepted",
                        note,
                        {"message_id": message_id, "status": "accepted", "needs_executor": True},
                    )

                shutil.move(str(path), str(ARCHIVE / path.name))


            def main() -> None:
                INBOX.mkdir(parents=True, exist_ok=True)
                OUTBOX.mkdir(parents=True, exist_ok=True)
                ARCHIVE.mkdir(parents=True, exist_ok=True)
                _write_outbox("Agent Worker Online", "Mailbox worker started and polling inbox.", {"poll_seconds": POLL})
                while True:
                    for item in sorted(INBOX.glob("*.json")):
                        _process_message(item)
                    time.sleep(POLL)


            if __name__ == "__main__":
                main()
            """
        )
