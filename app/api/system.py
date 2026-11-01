from fastapi import APIRouter, Depends

from app.config import settings
from app.core.auth import current_user
from app.core.observability import langsmith_enabled
from app.db.commerce import Account

router = APIRouter(prefix="/api/system", tags=["系统状态"])


@router.get("/status")
async def status(user: Account = Depends(current_user)):
    return {"model_configured": bool(settings.chat_api_key and settings.chat_model and settings.chat_base_url),
            "retrieval_configured": bool(settings.embed_api_key and settings.rerank_api_key),
            "observability": {"provider": "langsmith", "enabled": langsmith_enabled(),
                              "project": settings.langsmith_project},
            "service_checks": "configuration_only"}
