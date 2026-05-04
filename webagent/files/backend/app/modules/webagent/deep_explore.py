from __future__ import annotations

from typing import Any

from app.modules.webagent.safety import detect_destructive_action


def score_action(item: dict[str, Any], aggression: str = "normal") -> int:
    role = str(item.get("role") or "").lower()
    text = str(item.get("text") or "").lower()
    base = 10
    if role in {"button", "link", "menuitem", "tab", "checkbox", "radio", "textbox", "combobox"}:
        base += 10
    if any(token in text for token in ("next", "continue", "open", "details", "expand", "upload")):
        base += 8
    if any(token in text for token in ("delete", "remove", "reset", "logout", "pay", "purchase", "submit")):
        base -= 20
    if aggression == "aggressive":
        base += 10
    if aggression == "safe":
        base -= 6
    return base


def build_deep_explore_plan(
    *,
    items: list[dict[str, Any]],
    aggression: str = "normal",
    allow_destructive: bool = False,
    max_actions: int = 200,
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in items:
        info = detect_destructive_action(
            label=str(item.get("label") or ""),
            text=str(item.get("text") or ""),
            selector=str(item.get("selector") or ""),
        )
        row = dict(item)
        row["score"] = score_action(row, aggression=aggression)
        row["destructive"] = info
        if info["is_destructive"] and not allow_destructive:
            blocked.append(row)
            continue
        scored.append(row)

    scored.sort(key=lambda r: int(r.get("score") or 0), reverse=True)
    selected = scored[: max(1, max_actions)]
    return {
        "aggression": aggression,
        "allow_destructive": allow_destructive,
        "selected_actions": selected,
        "blocked_actions": blocked,
        "coverage": {
            "input_actions": len(items),
            "selected": len(selected),
            "blocked": len(blocked),
        },
    }
