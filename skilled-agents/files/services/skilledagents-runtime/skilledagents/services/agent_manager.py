from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from skilledagents.models.agent import AgentCreate, AgentUpdate
from skilledagents.models.skill import SkillCreate, SkillDetail
from skilledagents.models.template import AgentTemplateDetail, AgentTemplateSummary
from skilledagents.services.template_service import AgentTemplateService


class AgentManager:
    def __init__(
        self,
        db_path: Path,
        workspaces_root: Path,
        skills_root: Path,
        template_service: AgentTemplateService,
    ) -> None:
        self.db_path = db_path
        self.workspaces_root = workspaces_root
        self.skills_root = skills_root
        self.template_service = template_service
        self.workspaces_root.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    agent_type TEXT NOT NULL,
                    runtime TEXT NOT NULL,
                    model_provider TEXT,
                    model_name TEXT,
                    model_settings TEXT NOT NULL DEFAULT '{}',
                    workspace_path TEXT NOT NULL,
                    env_config TEXT NOT NULL DEFAULT '{}',
                    flags TEXT NOT NULL DEFAULT '{}',
                    network_access INTEGER NOT NULL DEFAULT 0,
                    sandbox_mode TEXT NOT NULL DEFAULT 'workspace-write',
                    yolo_mode INTEGER NOT NULL DEFAULT 0,
                    template_id TEXT,
                    specialization_mode TEXT NOT NULL DEFAULT 'strict',
                    role_identity TEXT,
                    domain_focus TEXT,
                    execution_mode TEXT,
                    allowed_tools TEXT NOT NULL DEFAULT '[]',
                    runtime_policies TEXT NOT NULL DEFAULT '{}',
                    saved_prompts TEXT NOT NULL DEFAULT '{}',
                    specialization_metadata TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'created',
                    active_run_id TEXT,
                    active_pid INTEGER,
                    last_run_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_skills (
                    agent_id TEXT NOT NULL,
                    skill_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(agent_id, skill_id)
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    command TEXT,
                    status TEXT NOT NULL,
                    pid INTEGER,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    exit_code INTEGER,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS agent_logs (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    run_id TEXT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS state_transitions (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    reason TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_snapshots (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'deploy',
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_agents_columns(conn)
            conn.commit()

    def _ensure_agents_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(agents)").fetchall()}
        required = {
            "template_id": "TEXT",
            "specialization_mode": "TEXT NOT NULL DEFAULT 'strict'",
            "role_identity": "TEXT",
            "domain_focus": "TEXT",
            "execution_mode": "TEXT",
            "allowed_tools": "TEXT NOT NULL DEFAULT '[]'",
            "runtime_policies": "TEXT NOT NULL DEFAULT '{}'",
            "saved_prompts": "TEXT NOT NULL DEFAULT '{}'",
            "specialization_metadata": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, ddl in required.items():
            if name in columns:
                continue
            conn.execute(f"ALTER TABLE agents ADD COLUMN {name} {ddl}")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _parse_skill_summary(self, skill_dir: Path) -> dict | None:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        lines = skill_md.read_text(encoding="utf-8", errors="ignore").splitlines()
        name = skill_dir.name
        description = ""
        for line in lines[:40]:
            clean = line.strip()
            if not clean:
                continue
            if clean.startswith("# "):
                name = clean[2:].strip() or name
                continue
            if clean.startswith("#"):
                continue
            description = clean
            break

        metadata_path = skill_dir / "skill.json"
        metadata: dict = {}
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                metadata = {}

        skill_id = str(metadata.get("id") or skill_dir.name).strip() or skill_dir.name
        slug = str(metadata.get("slug") or skill_id).strip() or skill_id
        version = str(metadata.get("version") or "1.0.0").strip() or "1.0.0"
        category = str(metadata.get("category") or "general").strip() or "general"
        tags = [str(tag).strip() for tag in list(metadata.get("tags") or []) if str(tag).strip()]
        effective_name = str(metadata.get("name") or name).strip() or skill_id
        effective_desc = str(metadata.get("description") or description).strip()
        checksum = hashlib.sha256(skill_md.read_bytes()).hexdigest()
        return {
            "id": skill_id,
            "slug": slug,
            "name": effective_name,
            "version": version,
            "description": effective_desc,
            "category": category,
            "tags": tags,
            "path": str(skill_dir),
            "checksum": checksum,
        }

    def _build_virtual_skill(self, skill_id: str, template_ids: list[str]) -> dict:
        return {
            "id": skill_id,
            "slug": skill_id,
            "name": skill_id.replace("-", " ").title(),
            "version": "template-ref",
            "description": f"Template-referenced skill ({', '.join(template_ids)}). Add this skill to provide implementation details.",
            "category": "template",
            "tags": ["template-referenced"],
            "path": "",
            "checksum": None,
        }

    def _row_to_agent(self, row: sqlite3.Row) -> dict:
        with self._connect() as conn:
            skill_rows = conn.execute(
                "SELECT skill_id FROM agent_skills WHERE agent_id = ? ORDER BY created_at ASC",
                (row["id"],),
            ).fetchall()
        return {
            "id": row["id"],
            "name": row["name"],
            "slug": row["slug"],
            "description": row["description"],
            "agent_type": row["agent_type"],
            "runtime": row["runtime"],
            "model_provider": row["model_provider"],
            "model_name": row["model_name"],
            "model_settings": json.loads(row["model_settings"] or "{}"),
            "workspace_path": row["workspace_path"],
            "selected_skills": [r["skill_id"] for r in skill_rows],
            "env_config": json.loads(row["env_config"] or "{}"),
            "flags": json.loads(row["flags"] or "{}"),
            "network_access": bool(row["network_access"]),
            "sandbox_mode": row["sandbox_mode"],
            "yolo_mode": bool(row["yolo_mode"]),
            "template_id": row["template_id"],
            "specialization_mode": row["specialization_mode"] or "strict",
            "role_identity": row["role_identity"],
            "domain_focus": row["domain_focus"],
            "execution_mode": row["execution_mode"],
            "allowed_tools": json.loads(row["allowed_tools"] or "[]"),
            "runtime_policies": json.loads(row["runtime_policies"] or "{}"),
            "saved_prompts": json.loads(row["saved_prompts"] or "{}"),
            "specialization_metadata": json.loads(row["specialization_metadata"] or "{}"),
            "status": row["status"],
            "last_run_at": row["last_run_at"],
            "last_error": row["last_error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_templates(self) -> list[AgentTemplateSummary]:
        return self.template_service.list_templates()

    def get_template(self, template_id: str) -> AgentTemplateDetail | None:
        return self.template_service.get_template(template_id)

    def _apply_specialization(self, data: dict) -> dict:
        template_id = data.get("template_id")
        if not template_id:
            return data
        template = self.get_template(str(template_id))
        if template is None:
            raise ValueError(f"unknown template_id: {template_id}")
        specialized, _warnings = self.template_service.apply_specialization(data, template)
        return specialized

    def _workspace_for(self, slug: str, agent_id: str, explicit_path: str | None = None) -> Path:
        if explicit_path:
            return Path(explicit_path).expanduser().resolve()
        return (self.workspaces_root / f"{slug}-{agent_id[:8]}").resolve()

    def _record_transition(
        self,
        conn: sqlite3.Connection,
        agent_id: str,
        from_status: str | None,
        to_status: str,
        reason: str,
        metadata: dict | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO state_transitions(id, agent_id, from_status, to_status, reason, metadata, created_at)
            VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                from_status,
                to_status,
                reason,
                json.dumps(metadata or {}),
                self._now(),
            ),
        )

    def create_agent(self, payload: AgentCreate) -> dict:
        create_data = self._apply_specialization(payload.model_dump())
        payload = AgentCreate(**create_data)
        now = self._now()
        with self._connect() as conn:
            agent_id = conn.execute("SELECT lower(hex(randomblob(16))) AS id").fetchone()["id"]
            workspace_path = str(self._workspace_for(payload.slug, agent_id, payload.workspace_path))
            conn.execute(
                """
                INSERT INTO agents(
                    id, name, slug, description, agent_type, runtime,
                    model_provider, model_name, model_settings,
                    workspace_path, env_config, flags, network_access,
                    sandbox_mode, yolo_mode, template_id, specialization_mode,
                    role_identity, domain_focus, execution_mode, allowed_tools,
                    runtime_policies, saved_prompts, specialization_metadata,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?)
                """,
                (
                    agent_id,
                    payload.name,
                    payload.slug,
                    payload.description,
                    payload.agent_type,
                    payload.runtime,
                    payload.model_provider,
                    payload.model_name,
                    json.dumps(payload.model_settings),
                    workspace_path,
                    json.dumps(payload.env_config),
                    json.dumps(payload.flags),
                    int(payload.network_access),
                    payload.sandbox_mode,
                    int(payload.yolo_mode),
                    payload.template_id,
                    payload.specialization_mode,
                    payload.role_identity,
                    payload.domain_focus,
                    payload.execution_mode,
                    json.dumps(payload.allowed_tools),
                    json.dumps(payload.runtime_policies),
                    json.dumps(payload.saved_prompts),
                    json.dumps(payload.specialization_metadata),
                    now,
                    now,
                ),
            )
            for skill_id in payload.selected_skills:
                conn.execute(
                    "INSERT OR IGNORE INTO agent_skills(agent_id, skill_id, created_at) VALUES (?, ?, ?)",
                    (agent_id, skill_id, now),
                )
            self._record_transition(conn, agent_id, None, "created", "agent created")
            conn.commit()
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return self._row_to_agent(row)

    def list_agents(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
        return [self._row_to_agent(r) for r in rows]

    def delete_all_agents(self) -> dict[str, int]:
        with self._connect() as conn:
            runs = int(conn.execute("SELECT COUNT(*) AS n FROM agent_runs").fetchone()["n"])
            logs = int(conn.execute("SELECT COUNT(*) AS n FROM agent_logs").fetchone()["n"])
            transitions = int(conn.execute("SELECT COUNT(*) AS n FROM state_transitions").fetchone()["n"])
            snapshots = int(conn.execute("SELECT COUNT(*) AS n FROM agent_snapshots").fetchone()["n"])
            links = int(conn.execute("SELECT COUNT(*) AS n FROM agent_skills").fetchone()["n"])
            agents = int(conn.execute("SELECT COUNT(*) AS n FROM agents").fetchone()["n"])

            conn.execute("DELETE FROM agent_logs")
            conn.execute("DELETE FROM agent_runs")
            conn.execute("DELETE FROM state_transitions")
            conn.execute("DELETE FROM agent_snapshots")
            conn.execute("DELETE FROM agent_skills")
            conn.execute("DELETE FROM agents")
            conn.commit()
        return {
            "agents_deleted": agents,
            "agent_skills_deleted": links,
            "runs_deleted": runs,
            "logs_deleted": logs,
            "transitions_deleted": transitions,
            "snapshots_deleted": snapshots,
        }

    def merge_flags(self, agent_id: str, patch: dict) -> dict | None:
        agent = self.get_agent(agent_id)
        if agent is None:
            return None
        merged = {**dict(agent.get("flags") or {}), **dict(patch or {})}
        return self.update_agent(agent_id, AgentUpdate(flags=merged))

    def get_agent(self, agent_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return None if row is None else self._row_to_agent(row)

    def get_status(self, agent_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, status, active_pid, active_run_id, last_run_at, last_error, updated_at
                FROM agents WHERE id = ?
                """,
                (agent_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "agent_id": row["id"],
            "status": row["status"],
            "pid": row["active_pid"],
            "active_run_id": row["active_run_id"],
            "last_run_at": row["last_run_at"],
            "last_error": row["last_error"],
            "updated_at": row["updated_at"],
        }

    def create_snapshot(self, agent_id: str, snapshot: dict, reason: str = "deploy") -> dict:
        now = self._now()
        with self._connect() as conn:
            snapshot_id = conn.execute("SELECT lower(hex(randomblob(16))) AS id").fetchone()["id"]
            conn.execute(
                """
                INSERT INTO agent_snapshots(id, agent_id, reason, snapshot_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snapshot_id, agent_id, reason, json.dumps(snapshot), now),
            )
            conn.commit()
        return {"id": snapshot_id, "agent_id": agent_id, "reason": reason, "snapshot": snapshot, "created_at": now}

    def list_snapshots(self, agent_id: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, agent_id, reason, snapshot_json, created_at
                FROM agent_snapshots
                WHERE agent_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "reason": row["reason"],
                "snapshot": json.loads(row["snapshot_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def latest_snapshot(self, agent_id: str) -> dict | None:
        items = self.list_snapshots(agent_id, limit=1)
        return items[0] if items else None

    def update_agent(self, agent_id: str, payload: AgentUpdate) -> dict | None:
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        current = self.get_agent(agent_id)
        if current is None:
            return None
        if not updates:
            return current

        requested_mode = str(updates.get("specialization_mode") or current.get("specialization_mode") or "strict").lower()
        if (
            "role_identity" in updates
            and current.get("role_identity")
            and updates["role_identity"] != current["role_identity"]
            and requested_mode != "custom"
        ):
            raise ValueError("role_identity is locked unless specialization_mode is 'custom'")

        merged = {**current, **updates}
        if merged.get("template_id"):
            merged = self._apply_specialization(merged)
            updates = {k: merged[k] for k in updates.keys() | {"template_id", "specialization_mode", "role_identity", "domain_focus", "execution_mode", "allowed_tools", "runtime_policies", "saved_prompts", "specialization_metadata"} if k in merged}

        assignments = []
        values: list = []
        json_fields = {"model_settings", "env_config", "flags", "allowed_tools", "runtime_policies", "saved_prompts", "specialization_metadata"}
        for key, value in updates.items():
            assignments.append(f"{key} = ?")
            values.append(json.dumps(value) if key in json_fields else value)

        values.append(self._now())
        values.append(agent_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE agents SET {', '.join(assignments)}, updated_at = ? WHERE id = ?",
                values,
            )
            conn.commit()
        return self.get_agent(agent_id)

    def set_status(
        self,
        agent_id: str,
        to_status: str,
        reason: str,
        *,
        active_run_id: str | None = None,
        active_pid: int | None = None,
        last_error: str | None = None,
        last_run_at: str | None = None,
        metadata: dict | None = None,
    ) -> dict | None:
        with self._connect() as conn:
            current = conn.execute(
                "SELECT status FROM agents WHERE id = ?",
                (agent_id,),
            ).fetchone()
            if current is None:
                return None
            conn.execute(
                """
                UPDATE agents
                SET status = ?, active_run_id = ?, active_pid = ?,
                    last_error = ?, last_run_at = COALESCE(?, last_run_at), updated_at = ?
                WHERE id = ?
                """,
                (
                    to_status,
                    active_run_id,
                    active_pid,
                    last_error,
                    last_run_at,
                    self._now(),
                    agent_id,
                ),
            )
            self._record_transition(conn, agent_id, current["status"], to_status, reason, metadata)
            conn.commit()
        return self.get_agent(agent_id)

    def add_skill(self, agent_id: str, skill_id: str) -> bool:
        agent = self.get_agent(agent_id)
        if agent is None:
            return False
        template_id = agent.get("template_id")
        if template_id and str(agent.get("specialization_mode", "strict")).lower() == "strict":
            template = self.get_template(str(template_id))
            if template and template.allowed_skills and skill_id not in set(template.allowed_skills):
                raise ValueError(f"skill '{skill_id}' is not allowed by template '{template_id}' in strict mode")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO agent_skills(agent_id, skill_id, created_at) VALUES (?, ?, ?)",
                (agent_id, skill_id, self._now()),
            )
            conn.commit()
        return True

    def remove_skill(self, agent_id: str, skill_id: str) -> bool:
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
                (agent_id, skill_id),
            ).rowcount
            conn.commit()
        return deleted > 0

    def list_skills(self) -> list[dict]:
        skills_by_id: dict[str, dict] = {}
        if self.skills_root.exists():
            for candidate in sorted(self.skills_root.iterdir()):
                if not candidate.is_dir():
                    continue
                summary = self._parse_skill_summary(candidate)
                if summary is None:
                    continue
                skills_by_id[summary["id"]] = summary

        for skill_id, templates in self.template_service.template_skill_references().items():
            if skill_id not in skills_by_id:
                skills_by_id[skill_id] = self._build_virtual_skill(skill_id, templates)

        return [skills_by_id[key] for key in sorted(skills_by_id)]

    def get_skill(self, skill_id: str) -> SkillDetail | None:
        for skill in self.list_skills():
            if skill["id"] != skill_id:
                continue
            if skill["path"]:
                skill_md = Path(skill["path"]) / "SKILL.md"
                body = skill_md.read_text(encoding="utf-8", errors="ignore") if skill_md.exists() else ""
                meta_path = Path(skill["path"]) / "skill.json"
                metadata = {}
                if meta_path.exists():
                    try:
                        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        metadata = {}
                metadata = {"has_skill_md": skill_md.exists(), **metadata}
                return SkillDetail(**skill, readme=body, metadata=metadata)

            refs = self.template_service.template_skill_references().get(skill_id, [])
            return SkillDetail(
                **skill,
                readme=(
                    f"# {skill['name']}\n\n"
                    "This skill appears in template constraints but has no local implementation yet.\n\n"
                    f"Referenced by templates: {', '.join(refs) if refs else 'unknown'}."
                ),
                metadata={"virtual": True, "template_references": refs},
            )
        return None

    def create_skill(self, payload: SkillCreate) -> SkillDetail:
        skill_id = payload.id.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", skill_id):
            raise ValueError("skill id must match [a-z0-9][a-z0-9-]{1,62}")
        skill_dir = self.skills_root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)

        if any(s["id"] == skill_id and s["path"] == "" for s in self.list_skills()):
            # If this id existed only as virtual template reference, creation materializes it.
            pass
        elif any(s["id"] == skill_id and s["path"] for s in self.list_skills()):
            raise ValueError("skill already exists")

        display_name = (payload.name or skill_id.replace("-", " ").title()).strip()
        description = payload.description.strip()
        readme = (payload.readme or "").strip()
        if not readme:
            readme = (
                f"# {display_name}\n\n"
                f"{description or 'Custom skill.'}\n\n"
                "## Usage\n\n"
                "Describe how this skill should be used by agents."
            )
        (skill_dir / "SKILL.md").write_text(readme.rstrip() + "\n", encoding="utf-8")

        skill_meta = {
            "id": skill_id,
            "slug": skill_id,
            "name": display_name,
            "version": payload.version.strip() or "1.0.0",
            "description": description,
            "category": payload.category.strip() or "custom",
            "tags": [str(tag).strip() for tag in payload.tags if str(tag).strip()],
            "created_at": self._now(),
        }
        (skill_dir / "skill.json").write_text(json.dumps(skill_meta, indent=2) + "\n", encoding="utf-8")

        skill = self.get_skill(skill_id)
        if skill is None:
            raise ValueError("failed to create skill")
        return skill

    def create_run(self, agent_id: str, command: str | None) -> str:
        now = self._now()
        with self._connect() as conn:
            run_id = conn.execute("SELECT lower(hex(randomblob(16))) AS id").fetchone()["id"]
            conn.execute(
                """
                INSERT INTO agent_runs(id, agent_id, command, status, started_at)
                VALUES (?, ?, ?, 'starting', ?)
                """,
                (run_id, agent_id, command, now),
            )
            conn.commit()
        return run_id

    def mark_run_started(self, run_id: str, pid: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE agent_runs SET status = 'running', pid = ? WHERE id = ?",
                (pid, run_id),
            )
            conn.commit()

    def mark_run_finished(self, run_id: str, exit_code: int, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = CASE WHEN ? = 0 THEN 'completed' ELSE 'failed' END,
                    ended_at = ?, exit_code = ?, error = ?
                WHERE id = ?
                """,
                (exit_code, self._now(), exit_code, error, run_id),
            )
            conn.commit()
