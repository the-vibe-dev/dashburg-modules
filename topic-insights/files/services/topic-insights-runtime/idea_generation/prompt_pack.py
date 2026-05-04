from __future__ import annotations

def idea_asset_prompts(idea_name: str, core_problem: str, solution: str) -> dict:
    # Prompts meant for image models or design tools; stored with each run
    logo_prompt = (
        f"Create a clean, modern app logo for '{idea_name}'. "
        f"Style: simple, bold, minimal icon, high contrast, flat vector, no mockups. "
        f"Theme should communicate: {core_problem}. "
        f"Include an icon and wordmark. Background transparent."
    )
    landing_prompt = (
        f"Write a concise landing page for {idea_name}. "
        f"Problem: {core_problem}. Solution: {solution}. "
        f"Include: hero headline, subheadline, 3 benefits, 3 features, pricing, FAQ, CTA."
    )
    build_prompt = (
        f"You are a senior full-stack engineer. Build an MVP for {idea_name}. "
        f"Scope: keep it simple. Include auth, core workflow, and Stripe subscription. "
        f"Use the solution: {solution}."
    )
    return {"logo_prompt": logo_prompt, "landing_prompt": landing_prompt, "build_prompt": build_prompt}


def landing_page_draft_prompt(idea_name: str, core_problem: str, solution: str) -> str:
    return (
        f"Write a landing page draft for {idea_name}.\n"
        f"Problem: {core_problem}\nSolution: {solution}\n\n"
        "Requirements:\n"
        "- Hero headline + subheadline\n"
        "- 3 bullet benefits\n"
        "- 3 core features\n"
        "- Pricing section\n"
        "- CTA\n"
        "Return plain text only."
    )
