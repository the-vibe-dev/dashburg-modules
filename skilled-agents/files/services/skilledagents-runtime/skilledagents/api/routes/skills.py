from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from skilledagents.models.skill import SkillCreate

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
def list_skills(request: Request) -> list[dict]:
    return request.app.state.agent_manager.list_skills()


@router.get("/{skill_id}")
def get_skill(skill_id: str, request: Request) -> dict:
    skill = request.app.state.agent_manager.get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return skill.model_dump()


@router.post("")
def create_skill(payload: SkillCreate, request: Request) -> dict:
    try:
        skill = request.app.state.agent_manager.create_skill(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return skill.model_dump()
