import logging
from functools import lru_cache

from app.config import settings

logger = logging.getLogger(__name__)


def langsmith_enabled() -> bool:
    return bool(settings.langsmith_tracing and settings.langsmith_api_key)


@lru_cache(maxsize=4)
def _client(api_key: str, endpoint: str, workspace: str, hide_inputs: bool):
    from langsmith import Client

    return Client(api_key=api_key, api_url=endpoint, hide_inputs=hide_inputs,
                  **({"workspace_id": workspace} if workspace else {}))


def get_langsmith():
    if not langsmith_enabled():
        return None
    return _client(settings.langsmith_api_key, settings.langsmith_endpoint,
                   settings.langsmith_workspace_id, settings.langsmith_hide_inputs)


def attach_observability(graph):
    client = get_langsmith()
    if client is None:
        return graph
    from langchain_core.tracers.langchain import LangChainTracer

    tracer = LangChainTracer(client=client, project_name=settings.langsmith_project)
    return graph.with_config({"callbacks": [tracer], "tags": ["eshop-assistant"]})


def tag_intent(intent: str, confidence: float) -> None:
    if not langsmith_enabled():
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        run = get_current_run_tree()
        if run is not None:
            run.add_metadata({"intent": intent, "intent_confidence": confidence})
            run.add_tags([f"intent:{intent}"])
    except Exception:
        logger.warning("LangSmith 意图标记失败", exc_info=True)
