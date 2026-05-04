from __future__ import annotations
import os
from pathlib import Path
from core.config import settings
from reports.html_renderer import render_report
from reports.json_export import export_json, write_json
from idea_generation.logo import svg_logo
from storage.models import PainCluster, Idea

def export_reports(clusters: list[PainCluster], ideas: list[Idea], title: str, notes: list[str] | None = None) -> dict:
    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # write simple SVG logos for each idea
    logos_dir = reports_dir / "logos"
    logos_dir.mkdir(parents=True, exist_ok=True)
    for i in ideas:
        (logos_dir / f"{i.idea_id}.svg").write_text(svg_logo(i.idea_name), encoding="utf-8")

    html = render_report(title=title, clusters=clusters, ideas=ideas, notes=notes)
    html_path = reports_dir / "latest_report.html"
    html_path.write_text(html, encoding="utf-8")

    json_path = reports_dir / "latest_report.json"
    write_json(str(json_path), export_json(clusters, ideas))

    return {"html": str(html_path), "json": str(json_path)}
