from __future__ import annotations
from pathlib import Path
from core.http_client import run_async
from llm.router import LLMRouter
from idea_generation.prompt_pack import landing_page_draft_prompt
from core.config import settings

EVAL_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "evaluation.md"

def evaluate_idea(idea: dict, cluster_label: str, examples: list[str]) -> dict:
    system = "You are a ruthless startup evaluator. Be harsh and practical."
    user = EVAL_PROMPT.read_text(encoding="utf-8") + "\n\nCLUSTER:\n" + cluster_label + "\n\nIDEA_JSON:\n" + str(idea) + "\n\nPAIN_EXAMPLES:\n- " + "\n- ".join(examples[:12])
    router = LLMRouter()
    model = settings.openai_model_eval if settings.llm_provider == "openai" else settings.ollama_model
    return run_async(router.chat_json(system=system, user=user, model=model, operation="idea_eval"))

def generate_landing_copy(idea_name: str, core_problem: str, solution: str) -> str:
    system = "You write concise high-converting landing page copy."
    user = landing_page_draft_prompt(idea_name, core_problem, solution)
    # Use chat_json is JSON-only; we want plain text, so call the underlying provider using chat_json wrapper? simplest: request JSON with text field.
    router = LLMRouter()
    model = settings.openai_model_eval if settings.llm_provider == "openai" else settings.ollama_model
    data = run_async(router.chat_json(system, "Return JSON only: {\"landing_copy\": \"...\"}\n\n"+user, model=model, operation="landing_copy"))
    return data.get("landing_copy","")

def evaluate_ideas_batch(ideas: list[dict], cluster_labels: list[str], examples_by_cluster: list[list[str]]) -> list[dict]:
    system = "You are a ruthless startup evaluator. Be harsh and practical."
    lines = ["Return JSON only: {\"items\": [{\"index\": 0, \"ctr_prediction\": 0.0, \"would_build_confidence\": 0.0, \"landing_copy\": \"...\"}]}"]
    for i, idea in enumerate(ideas):
        examples = examples_by_cluster[i][:10]
        lines.append(
            f"INDEX {i}\nCLUSTER:\n{cluster_labels[i]}\nIDEA_JSON:\n{idea}\n\nPAIN_EXAMPLES:\n- " + "\n- ".join(examples)
        )
    user = EVAL_PROMPT.read_text(encoding="utf-8") + "\n\n" + "\n\n".join(lines)
    router = LLMRouter()
    model = settings.openai_model_eval if settings.llm_provider == "openai" else settings.ollama_model
    data = run_async(router.chat_json(system=system, user=user, model=model, operation="eval_batch"))
    return data.get("items") or []
