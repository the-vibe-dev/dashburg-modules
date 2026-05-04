from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from skilledagents.models.template import AgentTemplateDetail, AgentTemplateSummary


BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "marketing-ideas-agent",
        "name": "Marketing Ideas Agent",
        "description": "Generates campaign concepts, angles, and messaging variants for a target audience.",
        "category": "marketing",
        "strict_by_default": True,
        "version": "1.0.0",
        "agent_type": "marketing_ideas_agent",
        "domain_focus": "marketing ideation",
        "execution_mode": "brainstorm",
        "runtime": "python",
        "model_provider": "openai",
        "model_name": "gpt-5",
        "recommended_skills": ["idea-generator", "tone-optimizer"],
        "allowed_skills": ["idea-generator", "tone-optimizer", "brand-voice", "campaign-brief-parser"],
        "allowed_tools": ["filesystem", "markdown_writer"],
        "disallowed_capabilities": ["shell_exec", "network_access", "yolo_mode"],
        "default_prompts": {
            "system": "You are a focused marketing ideation agent. Produce actionable campaign ideas with rationale.",
            "style": "Concise, audience-aware, and channel-specific outputs.",
        },
        "runtime_policies": {"max_output_items": 20, "require_brief_context": True},
        "execution_expectations": [
            "Ground ideas in audience pain points.",
            "Return campaign concepts, hooks, and a short execution plan.",
        ],
        "ui_hints": {"accent": "amber", "wizard_tip": "Use strict mode for campaign consistency."},
    },
    {
        "id": "blog-reader-agent",
        "name": "Blog Reader Agent",
        "description": "Reads long-form content and returns concise summaries with key takeaways.",
        "category": "content",
        "strict_by_default": True,
        "version": "1.0.0",
        "agent_type": "blog_reader_agent",
        "domain_focus": "blog and article analysis",
        "execution_mode": "reader",
        "runtime": "python",
        "model_provider": "openai",
        "model_name": "gpt-5",
        "recommended_skills": ["summarizer", "extract-key-points"],
        "allowed_skills": ["summarizer", "extract-key-points", "citation-builder"],
        "allowed_tools": ["filesystem", "url_fetch"],
        "disallowed_capabilities": ["shell_exec", "yolo_mode"],
        "default_prompts": {
            "system": "You read and synthesize blog posts. Keep summaries factual and source-linked.",
            "output": "Return summary, key claims, and action items.",
        },
        "runtime_policies": {"max_input_chars": 250000, "require_citations": True},
        "execution_expectations": [
            "Summarize clearly without inventing facts.",
            "Include references to source sections when possible.",
        ],
        "ui_hints": {"accent": "teal", "wizard_tip": "Attach citation-related skills for traceability."},
    },
    {
        "id": "web-research-agent",
        "name": "Web Research Agent",
        "description": "Finds, compares, and synthesizes web sources for a research question.",
        "category": "research",
        "strict_by_default": False,
        "version": "1.0.0",
        "agent_type": "web_research_agent",
        "domain_focus": "web research and synthesis",
        "execution_mode": "research",
        "runtime": "python",
        "model_provider": "openai",
        "model_name": "gpt-5",
        "recommended_skills": ["web-search", "source-summarizer"],
        "allowed_skills": ["web-search", "source-summarizer", "fact-check", "table-builder"],
        "allowed_tools": ["filesystem", "url_fetch", "http_client"],
        "disallowed_capabilities": ["shell_exec"],
        "default_prompts": {
            "system": "You are a web research agent. Collect evidence from multiple sources before concluding.",
            "output": "Return findings, confidence, and open questions.",
        },
        "runtime_policies": {"max_sources": 20, "min_sources": 3},
        "execution_expectations": [
            "Use multiple independent sources.",
            "Separate verified findings from assumptions.",
        ],
        "ui_hints": {"accent": "blue", "wizard_tip": "Custom mode is useful for niche research tooling."},
    },
]


class AgentTemplateService:
    def __init__(self, templates_path: Path | None = None) -> None:
        self.templates_path = templates_path
        self._templates = self._load_templates()

    @classmethod
    def from_env(cls) -> "AgentTemplateService":
        raw_path = os.getenv("SKILLEDAGENTS_TEMPLATES_PATH", "").strip()
        return cls(Path(raw_path).expanduser().resolve() if raw_path else None)

    def _load_templates(self) -> dict[str, AgentTemplateDetail]:
        rows: list[dict[str, Any]]
        if self.templates_path and self.templates_path.exists():
            rows = json.loads(self.templates_path.read_text(encoding="utf-8"))
        else:
            rows = BUILTIN_TEMPLATES
        return {row["id"]: AgentTemplateDetail(**row) for row in rows}

    def list_templates(self) -> list[AgentTemplateSummary]:
        return [
            AgentTemplateSummary(
                id=item.id,
                name=item.name,
                description=item.description,
                category=item.category,
                strict_by_default=item.strict_by_default,
            )
            for item in self._templates.values()
        ]

    def get_template(self, template_id: str) -> AgentTemplateDetail | None:
        return self._templates.get(template_id)

    def template_skill_references(self) -> dict[str, list[str]]:
        refs: dict[str, list[str]] = {}
        for template in self._templates.values():
            skill_ids = list(
                dict.fromkeys(
                    [*template.recommended_skills, *template.allowed_skills]
                )
            )
            for skill_id in skill_ids:
                refs.setdefault(skill_id, []).append(template.id)
        return refs

    def apply_specialization(self, payload: dict[str, Any], template: AgentTemplateDetail) -> tuple[dict[str, Any], list[str]]:
        result = dict(payload)
        warnings: list[str] = []
        mode = str(result.get("specialization_mode") or ("strict" if template.strict_by_default else "custom")).lower()
        if mode not in {"strict", "custom"}:
            mode = "strict"

        selected_skills = list(result.get("selected_skills") or [])
        if mode == "strict":
            selected_skills = list(dict.fromkeys([*template.recommended_skills, *selected_skills]))
            if template.allowed_skills:
                selected_skills = [s for s in selected_skills if s in set(template.allowed_skills)]
            result["network_access"] = False if "network_access" in set(template.disallowed_capabilities) else bool(result.get("network_access"))
            result["yolo_mode"] = False if "yolo_mode" in set(template.disallowed_capabilities) else bool(result.get("yolo_mode"))
        else:
            if "network_access" in set(template.disallowed_capabilities) and result.get("network_access"):
                warnings.append("template discourages network_access")
            if "yolo_mode" in set(template.disallowed_capabilities) and result.get("yolo_mode"):
                warnings.append("template discourages yolo_mode")

        result["selected_skills"] = selected_skills
        result["template_id"] = template.id
        result["specialization_mode"] = mode
        result["role_identity"] = result.get("role_identity") or template.agent_type
        result["agent_type"] = result.get("agent_type") or template.agent_type
        result["domain_focus"] = result.get("domain_focus") or template.domain_focus
        result["execution_mode"] = result.get("execution_mode") or template.execution_mode
        result["runtime"] = result.get("runtime") or template.runtime
        result["model_provider"] = result.get("model_provider") or template.model_provider
        result["model_name"] = result.get("model_name") or template.model_name
        result["allowed_tools"] = list(result.get("allowed_tools") or template.allowed_tools)
        result["runtime_policies"] = {**template.runtime_policies, **dict(result.get("runtime_policies") or {})}
        result["saved_prompts"] = {**template.default_prompts, **dict(result.get("saved_prompts") or {})}
        result["specialization_metadata"] = {
            **dict(result.get("specialization_metadata") or {}),
            "template_version": template.version,
            "disallowed_capabilities": template.disallowed_capabilities,
            "execution_expectations": template.execution_expectations,
            "ui_hints": template.ui_hints,
            "warnings": warnings,
        }
        return result, warnings
