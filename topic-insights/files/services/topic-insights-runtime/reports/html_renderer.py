from __future__ import annotations
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from storage.models import PainCluster, Idea

TEMPLATES_DIR = Path(__file__).resolve().parents[0] / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

def render_report(title: str, clusters: list[PainCluster], ideas: list[Idea], notes: list[str] | None = None) -> str:
    tpl = env.get_template("report.html")
    return tpl.render(
        title=title,
        generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        clusters=clusters,
        ideas=ideas,
        notes=notes or [],
    )
