from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(raw: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower())
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "template"


_CORE8_PATHS: dict[str, int] = {
    "engineering/engineering-frontend-developer.md": 1,
    "engineering/engineering-backend-architect.md": 2,
    "engineering/engineering-devops-automator.md": 3,
    "design/design-ux-architect.md": 4,
    "project-management/project-manager-senior.md": 5,
    "testing/testing-reality-checker.md": 6,
    "specialized/agents-orchestrator.md": 7,
    "engineering/engineering-ai-engineer.md": 8,
}

_TOOL_LEARNING_BOOTSTRAP = (
    "## Tool Learning Bootstrap\\n"
    "- Before solving the task, map available capabilities in this environment.\\n"
    "- Inspect attached skills and their metadata/manifests first.\\n"
    "- Detect available runtimes and package managers relevant to your task (python/node/system tools).\\n"
    "- Prefer using already-installed tools and documented skills before introducing new dependencies.\\n"
    "- Record a short capability summary in your first response so future runs can reuse it.\\n"
)


class StarterTemplateService:
    def __init__(self, db_path: Path, storage_root: Path) -> None:
        self.db_path = db_path
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS starter_templates (
                    slug TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    template_version TEXT NOT NULL DEFAULT '0.0.1',
                    pack_version TEXT NOT NULL DEFAULT 'v1',
                    source_zip TEXT NOT NULL,
                    source_pack TEXT NOT NULL,
                    precedence INTEGER NOT NULL DEFAULT 0,
                    uses_webagent INTEGER NOT NULL DEFAULT 0,
                    imported_at TEXT NOT NULL,
                    template_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS starter_template_history (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL,
                    template_version TEXT NOT NULL,
                    pack_version TEXT NOT NULL,
                    source_zip TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    imported_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _pack_meta(self, zip_path: Path, pack_version: str | None = None) -> dict[str, Any]:
        name = zip_path.name.lower()
        inferred = pack_version or "v1"
        if "v2" in name:
            inferred = "v2"
        elif "v3" in name:
            inferred = "v3-additions"
        rank = {"v1": 100, "v2": 200, "v3-additions": 150}.get(inferred, 50)
        additions_only = inferred == "v3-additions"
        return {"pack_version": inferred, "precedence": rank, "additions_only": additions_only}

    def _normalize_compatibility(self, template: dict[str, Any]) -> dict[str, bool]:
        defaults = {
            "requires_browser": False,
            "requires_network": False,
            "requires_python": False,
            "requires_node": False,
            "requires_ocr": False,
            "requires_docs_tooling": False,
        }
        explicit = template.get("compatibility_badges") or {}
        for key in list(defaults):
            if key in template:
                explicit[key] = template[key]
        return {k: bool(explicit.get(k, defaults[k])) for k in defaults}

    def _extract_index_entries(self, index_json: Any) -> list[dict[str, Any]]:
        if isinstance(index_json, list):
            rows = index_json
        elif isinstance(index_json, dict):
            rows = index_json.get("templates") or index_json.get("agents") or index_json.get("items") or []
        else:
            rows = []
        out: list[dict[str, Any]] = []
        for item in rows:
            if isinstance(item, str):
                out.append({"path": item})
            elif isinstance(item, dict):
                out.append(item)
        return out

    def _read_template_json(self, extracted_root: Path, index_dir: Path, entry: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        raw_path = str(entry.get("path") or entry.get("dir") or "").strip()
        if not raw_path:
            if entry.get("slug") or entry.get("name"):
                return dict(entry), index_dir
            raise ValueError("index entry missing path/dir")
        candidates = [(index_dir / raw_path).resolve(), (extracted_root / raw_path).resolve()]
        if raw_path.startswith("starter_agents/"):
            candidates.append((extracted_root / raw_path[len("starter_agents/") :]).resolve())
        agent_json: Path | None = None
        for base in candidates:
            current = base / "agent.json" if base.is_dir() else base
            if current.is_dir():
                current = current / "agent.json"
            if current.exists():
                agent_json = current
                break
        if agent_json is None:
            agent_json = candidates[0] / "agent.json"
        if not agent_json.exists():
            raise ValueError(f"agent.json not found for entry path={raw_path}")
        data = json.loads(agent_json.read_text(encoding="utf-8"))
        return data, agent_json.parent

    def _normalize_template(self, raw: dict[str, Any], template_dir: Path, meta: dict[str, Any], source_zip: str) -> dict[str, Any]:
        slug = _slugify(str(raw.get("slug") or raw.get("id") or raw.get("name") or template_dir.name))
        name = str(raw.get("name") or slug)
        skills_raw = (
            raw.get("skills")
            or raw.get("selected_skills")
            or raw.get("recommended_skills")
            or ((raw.get("workspace_preview") or {}).get("skills_to_attach") if isinstance(raw.get("workspace_preview"), dict) else [])
            or []
        )
        skills: list[str] = []
        for item in skills_raw:
            if isinstance(item, str):
                skills.append(item)
            elif isinstance(item, dict) and item.get("slug"):
                skills.append(str(item["slug"]))
        deploy_meta = raw.get("deploy_mode") or {}
        recommended_mode = str(
            (deploy_meta.get("recommended") if isinstance(deploy_meta, dict) else deploy_meta)
            or raw.get("recommended_deploy_mode")
            or "sandboxed"
        )
        execution_mode = str(raw.get("execution_mode") or raw.get("mode") or "task")
        compatibility = self._normalize_compatibility(raw)
        skill_compat = raw.get("skill_compatibility_badges")
        if isinstance(skill_compat, dict):
            compatibility = {**compatibility, **{k: bool(v) for k, v in skill_compat.items()}}
        uses_webagent = bool(raw.get("uses_webagent") or (raw.get("webagent") or {}).get("enabled"))
        integration_hints = raw.get("integration_hints") or {}
        if isinstance(integration_hints, dict) and integration_hints.get("uses_network_webagent"):
            uses_webagent = True
        external_dependencies = list(raw.get("external_dependencies") or [])
        if uses_webagent and "webagent-playwright-analyzer" not in external_dependencies:
            external_dependencies.append("webagent-playwright-analyzer")
        workspace_preview = raw.get("workspace_preview") or {}
        files_to_create = list(workspace_preview.get("files_to_create") or raw.get("files_to_create") or [])
        dependencies = list(
            workspace_preview.get("dependencies_to_install")
            or raw.get("dependencies")
            or raw.get("requirements")
            or []
        )
        tests = raw.get("tests") or raw.get("skill_tests") or {}
        validation_hook = tests.get("validation_hook") or raw.get("validation_hook")
        smoke_test = tests.get("smoke_test_command") or raw.get("smoke_test_command")

        return {
            "slug": slug,
            "name": name,
            "description": str(raw.get("description") or raw.get("purpose") or ""),
            "agent_type": str(raw.get("agent_type") or raw.get("archetype") or "specialized"),
            "template_version": str(raw.get("template_version") or raw.get("version") or "0.0.1"),
            "pack_version": meta["pack_version"],
            "source_zip": source_zip,
            "source_pack": Path(source_zip).name,
            "precedence": int(meta["precedence"]),
            "compatibility_badges": compatibility,
            "recommended_deploy_mode": recommended_mode,
            "deploy_modes": ["safe", "sandboxed", "networked", "yolo"],
            "execution_mode": execution_mode,
            "entrypoint": str(raw.get("entrypoint") or "run.sh"),
            "skills_to_attach": skills,
            "dependencies_to_install": dependencies,
            "files_to_create": files_to_create,
            "runtime": str(raw.get("runtime") or "python"),
            "model_provider": raw.get("model_provider"),
            "model_name": raw.get("model_name"),
            "runtime_flags": dict(raw.get("runtime_flags") or {}),
            "external_dependencies": external_dependencies,
            "uses_webagent": uses_webagent,
            "delegates_playwright": bool(raw.get("delegates_playwright") or uses_webagent),
            "readme_snippet": str(raw.get("summary") or raw.get("readme_snippet") or ""),
            "validation_hook": validation_hook,
            "smoke_test_command": smoke_test,
            "raw_template": raw,
        }

    def _parse_frontmatter(self, text: str) -> tuple[dict[str, str], str]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, text
        fm: dict[str, str] = {}
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
            line = lines[i].strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            fm[key.strip().lower()] = value.strip().strip("'\"")
        if end is None:
            return {}, text
        body = "\n".join(lines[end + 1 :]).strip()
        return fm, body

    def _record_history(
        self,
        conn: sqlite3.Connection,
        slug: str,
        template_version: str,
        pack_version: str,
        source_zip: str,
        action: str,
        details: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            INSERT INTO starter_template_history(
              id, slug, template_version, pack_version, source_zip, action, details, imported_at
            ) VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                template_version,
                pack_version,
                source_zip,
                action,
                json.dumps(details),
                _now(),
            ),
        )

    def _upsert_template(
        self,
        conn: sqlite3.Connection,
        normalized: dict[str, Any],
        source_zip: str,
        *,
        additions_only: bool,
    ) -> str:
        slug = normalized["slug"]
        existing = conn.execute(
            "SELECT slug, precedence, pack_version, source_zip FROM starter_templates WHERE slug = ?",
            (slug,),
        ).fetchone()

        action = "inserted"
        should_write = True
        if existing is not None:
            if additions_only:
                should_write = False
                action = "skipped_additions_overlap"
            elif int(normalized["precedence"]) >= int(existing["precedence"]):
                action = "replaced"
            else:
                should_write = False
                action = "skipped_lower_precedence"

        self._record_history(
            conn,
            slug=slug,
            template_version=normalized["template_version"],
            pack_version=normalized["pack_version"],
            source_zip=source_zip,
            action=action,
            details={"existing_pack": existing["pack_version"] if existing else None},
        )

        if not should_write:
            return action

        conn.execute(
            """
            INSERT INTO starter_templates(
                slug, name, description, template_version, pack_version,
                source_zip, source_pack, precedence, uses_webagent, imported_at, template_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                template_version=excluded.template_version,
                pack_version=excluded.pack_version,
                source_zip=excluded.source_zip,
                source_pack=excluded.source_pack,
                precedence=excluded.precedence,
                uses_webagent=excluded.uses_webagent,
                imported_at=excluded.imported_at,
                template_json=excluded.template_json
            """,
            (
                normalized["slug"],
                normalized["name"],
                normalized["description"],
                normalized["template_version"],
                normalized["pack_version"],
                normalized["source_zip"],
                normalized["source_pack"],
                normalized["precedence"],
                int(normalized["uses_webagent"]),
                _now(),
                json.dumps(normalized),
            ),
        )
        return action

    def import_pack(self, zip_path: str, pack_version: str | None = None) -> dict[str, Any]:
        src = Path(zip_path).expanduser().resolve()
        if not src.exists():
            raise ValueError(f"zip not found: {src}")
        meta = self._pack_meta(src, pack_version)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        extracted_root = self.storage_root / "imports" / f"{ts}_{src.stem}"
        extracted_root.mkdir(parents=True, exist_ok=True)
        with ZipFile(src, "r") as zf:
            zf.extractall(extracted_root)

        index_candidates = list(extracted_root.rglob("starter_agents/agents_index.json"))
        if not index_candidates:
            raise ValueError("starter_agents/agents_index.json not found in zip")
        index_path = index_candidates[0]
        index_json = json.loads(index_path.read_text(encoding="utf-8"))
        entries = self._extract_index_entries(index_json)
        if not entries:
            raise ValueError("agents_index.json has no templates")

        imported = 0
        replaced = 0
        skipped = 0
        with self._connect() as conn:
            for entry in entries:
                raw, template_dir = self._read_template_json(extracted_root, index_path.parent, entry)
                normalized = self._normalize_template(raw, template_dir, meta, str(src))
                action = self._upsert_template(conn, normalized, str(src), additions_only=bool(meta["additions_only"]))
                if action.startswith("skipped"):
                    skipped += 1
                elif action == "inserted":
                    imported += 1
                else:
                    replaced += 1
            conn.commit()
        return {
            "zip_path": str(src),
            "pack_version": meta["pack_version"],
            "entries_seen": len(entries),
            "inserted": imported,
            "replaced": replaced,
            "skipped": skipped,
        }

    def import_batch(self, zip_paths: list[str]) -> dict[str, Any]:
        results = [self.import_pack(path) for path in zip_paths]
        return {"count": len(results), "results": results}

    def clear_templates(self) -> dict[str, int]:
        with self._connect() as conn:
            templates_count = int(conn.execute("SELECT COUNT(*) AS n FROM starter_templates").fetchone()["n"])
            history_count = int(conn.execute("SELECT COUNT(*) AS n FROM starter_template_history").fetchone()["n"])
            conn.execute("DELETE FROM starter_templates")
            conn.execute("DELETE FROM starter_template_history")
            conn.commit()
        return {"templates_deleted": templates_count, "history_deleted": history_count}

    def import_agency_templates(
        self,
        root_path: str,
        *,
        purge_first: bool = False,
        seed_top_agents: bool = True,
    ) -> dict[str, Any]:
        root = Path(root_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"agency root not found: {root}")

        purge_result = {"templates_deleted": 0, "history_deleted": 0}
        if purge_first:
            purge_result = self.clear_templates()

        md_files = [
            p for p in root.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(root).parts)
        ]

        seen = 0
        imported = 0
        replaced = 0
        skipped = 0
        top_seeded: list[str] = []

        with self._connect() as conn:
            for path in sorted(md_files):
                rel = path.relative_to(root).as_posix()
                frontmatter, body = self._parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
                name = str(frontmatter.get("name") or "").strip()
                description = str(frontmatter.get("description") or "").strip()
                if not name or not description:
                    continue

                seen += 1
                category = path.relative_to(root).parts[0] if len(path.relative_to(root).parts) > 1 else "general"
                slug = _slugify(str(frontmatter.get("slug") or name))
                prompt = body.strip()
                if prompt:
                    prompt = f"{_TOOL_LEARNING_BOOTSTRAP}\n\n{prompt}"
                is_top = bool(seed_top_agents and rel in _CORE8_PATHS)
                top_rank = _CORE8_PATHS.get(rel)
                if is_top:
                    top_seeded.append(slug)

                normalized = {
                    "slug": slug,
                    "name": name,
                    "description": description,
                    "agent_type": _slugify(name).replace("-", "_"),
                    "template_version": "agency-main",
                    "pack_version": "agency-main",
                    "source_zip": str(root),
                    "source_pack": root.name,
                    "precedence": 1000 if is_top else 500,
                    "compatibility_badges": self._normalize_compatibility({}),
                    "recommended_deploy_mode": "sandboxed",
                    "deploy_modes": ["safe", "sandboxed", "networked", "yolo"],
                    "execution_mode": "task",
                    "entrypoint": "run.sh",
                    "skills_to_attach": [],
                    "dependencies_to_install": [],
                    "files_to_create": [],
                    "runtime": "python",
                    "model_provider": "openai",
                    "model_name": "gpt-5",
                    "runtime_flags": {},
                    "external_dependencies": [],
                    "uses_webagent": False,
                    "delegates_playwright": False,
                    "readme_snippet": prompt[:220],
                    "validation_hook": None,
                    "smoke_test_command": None,
                    "source_file": rel,
                    "category": category,
                    "is_top_agent": is_top,
                    "top_rank": top_rank,
                    "saved_prompts": {"system": prompt},
                    "prompt_system": prompt,
                    "raw_template": {"frontmatter": frontmatter, "source_file": rel},
                }
                action = self._upsert_template(conn, normalized, str(root), additions_only=False)
                if action.startswith("skipped"):
                    skipped += 1
                elif action == "inserted":
                    imported += 1
                else:
                    replaced += 1

            conn.commit()

        return {
            "root_path": str(root),
            "entries_seen": seen,
            "inserted": imported,
            "replaced": replaced,
            "skipped": skipped,
            "purge_first": purge_first,
            "purge_result": purge_result,
            "top_agents_seeded": sorted(top_seeded),
        }

    def list_templates(self, *, top_only: bool = False) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT slug, name, description, template_version, pack_version, source_zip, source_pack,
                       uses_webagent, imported_at, template_json
                FROM starter_templates
                """
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["template_json"] or "{}")
            is_top = bool(payload.get("is_top_agent"))
            if top_only and not is_top:
                continue
            out.append(
                {
                    "slug": row["slug"],
                    "name": row["name"],
                    "description": row["description"],
                    "template_version": row["template_version"],
                    "pack_version": row["pack_version"],
                    "source_zip": row["source_zip"],
                    "source_pack": row["source_pack"],
                    "uses_webagent": bool(row["uses_webagent"]),
                    "compatibility_badges": payload.get("compatibility_badges", {}),
                    "recommended_deploy_mode": payload.get("recommended_deploy_mode", "sandboxed"),
                    "imported_at": row["imported_at"],
                    "readme_snippet": payload.get("readme_snippet", ""),
                    "is_top_agent": is_top,
                    "top_rank": payload.get("top_rank"),
                    "category": payload.get("category") or "general",
                    "source_file": payload.get("source_file"),
                }
            )
        out.sort(key=lambda item: (0 if item.get("is_top_agent") else 1, int(item.get("top_rank") or 999), str(item["name"]).lower()))
        return out

    def get_template(self, slug: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT template_json FROM starter_templates WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row["template_json"] or "{}")
        payload.setdefault("slug", slug)
        return payload
