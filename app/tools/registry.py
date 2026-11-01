import importlib
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

WRITE_TOOLS: set[str] = {"create_ticket"}


@dataclass
class ToolSpec:
    name: str
    description: str
    json_schema: dict
    tool: BaseTool
    permission: str
    source: str
    mcp_server: str | None = None
    timeout: float | None = None
    max_retries: int | None = None
    inject_conversation: bool = False
    inject_user_id: bool = False
    inject_request_id: bool = False
    format_result: Callable[[dict], dict] | None = None


_BUILTIN: dict[str, ToolSpec] = {}
_scanned = False


def permission_for(name: str) -> str:
    return "write" if name in WRITE_TOOLS else "read"


def _json_schema_of(tool: BaseTool) -> dict:
    raw = getattr(tool, "args_schema", None)
    if isinstance(raw, dict):
        return raw
    tcs = getattr(tool, "tool_call_schema", None) or raw
    return tcs.model_json_schema()


def spec_from_langchain_tool(tool: BaseTool, *, source: str, mcp_server: str | None = None,
                             timeout: float | None = None, max_retries: int | None = None,
                             inject_conversation: bool = False, inject_user_id: bool = False,
                             inject_request_id: bool = False,
                             format_result: Callable | None = None) -> ToolSpec:
    return ToolSpec(name=tool.name, description=tool.description or "",
                    json_schema=_json_schema_of(tool), tool=tool,
                    permission=permission_for(tool.name), source=source, mcp_server=mcp_server,
                    timeout=timeout, max_retries=max_retries,
                    inject_conversation=inject_conversation, inject_user_id=inject_user_id,
                    inject_request_id=inject_request_id,
                    format_result=format_result)


def register(spec: ToolSpec) -> None:
    if spec.name in _BUILTIN:
        logger.warning("工具重名,丢弃后注册者 name=%s(先到者保留)", spec.name)
        return
    _BUILTIN[spec.name] = spec


def scan_builtin() -> None:
    global _scanned
    if _scanned:
        return
    _scanned = True
    from app.tools import builtin as pkg
    for m in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"{pkg.__name__}.{m.name}")
        except Exception:
            logger.exception("内置工具模块导入失败,跳过 module=%s", m.name)
    logger.info("内置工具注册完成:%s", sorted(_BUILTIN))


def builtin_specs() -> list[ToolSpec]:
    scan_builtin()
    return list(_BUILTIN.values())


def get_builtin_spec(name: str) -> ToolSpec | None:
    scan_builtin()
    return _BUILTIN.get(name)


async def get_all_specs() -> list[ToolSpec]:
    from app.tools import mcp_client
    merged: dict[str, ToolSpec] = {s.name: s for s in builtin_specs()}
    for s in await mcp_client.fetch_mcp_specs():
        if s.name in merged:
            logger.warning("MCP 工具与已注册工具重名,丢弃 name=%s server=%s", s.name, s.mcp_server)
            continue
        merged[s.name] = s
    return list(merged.values())
