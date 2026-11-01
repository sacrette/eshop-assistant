"""工具统一执行器。

每次调用按固定顺序走：参数校验 → 写操作确认 → 服务端字段注入 → 订单归属校验 → 调用 → 审计。
无论成功失败都返回带中文说明的 ToolMessage，让模型能据此纠错或如实告知用户，而不是编造结果。
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from langchain_core.messages import ToolMessage

from app.config import settings
from app.db import repository
from app.tools.registry import ToolSpec

logger = logging.getLogger(__name__)


_TRANSIENT = (asyncio.TimeoutError, TimeoutError, ConnectionError, httpx.TransportError)
_SUMMARY_LIMIT = 500


@dataclass
class ToolRun:
    tool_call_id: str
    name: str
    ok: bool
    tool_message: ToolMessage
    status: str
    retry_count: int = 0
    duration_ms: int = 0


def validate_args(spec: ToolSpec, args: dict) -> str | None:
    err = best_match(Draft202012Validator(spec.json_schema).iter_errors(args))
    if err is None:
        return None
    where = f"(字段 {err.json_path})" if err.json_path != "$" else ""
    return f"{err.message}{where}"


def _timeout_of(spec: ToolSpec) -> float:
    if spec.timeout is not None:
        return spec.timeout
    return settings.mcp_tool_timeout if spec.source == "mcp" else settings.tool_default_timeout


def _summarize(content: str) -> str:
    return content if len(content) <= _SUMMARY_LIMIT else content[:_SUMMARY_LIMIT] + "…(截断)"


def _format_content(spec: ToolSpec, result) -> str:
    if isinstance(result, list) and result and all(isinstance(b, dict) for b in result):
        texts = [b.get("text", "") for b in result if b.get("type") == "text"]
        if texts:
            result = "\n".join(texts)
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (json.JSONDecodeError, ValueError):
            return result
    if isinstance(result, dict) and result.get("error"):
        return json.dumps(result, ensure_ascii=False, default=str)
    if spec.format_result is not None and isinstance(result, dict):
        try:
            result = spec.format_result(result)
        except Exception:
            logger.exception("结果格式化钩子异常,降级透传原始结果 tool=%s", spec.name)
    return json.dumps(result, ensure_ascii=False, default=str)


async def _audit(conversation_id, tool_call_id, name, spec: ToolSpec | None, args,
                 result_summary, status, error_message, retry_count, duration_ms) -> None:
    logger.info("tool_run conv=%s tool=%s source=%s server=%s status=%s retry=%s duration_ms=%s%s",
                conversation_id or "-", name,
                spec.source if spec else "unknown",
                (spec.mcp_server if spec else None) or "-",
                status, retry_count, duration_ms,
                f" err={error_message[:80]!r}" if error_message else "")
    try:
        await repository.insert_tool_audit(
            conversation_id=conversation_id or None, tool_call_id=(tool_call_id or None) and tool_call_id[:64],
            tool_name=name[:128],
            tool_source=(spec.source if spec else "builtin"),
            mcp_server=(spec.mcp_server if spec else None),
            arguments=args or None, result_summary=result_summary, status=status,
            error_message=error_message and error_message[:500],
            retry_count=retry_count, duration_ms=duration_ms,
        )
    except Exception:
        logger.exception("审计写入失败(不影响工具执行) tool=%s status=%s", name, status)


async def execute_tool_call(
    tool_call: dict, conversation_id: int, specs: dict[str, ToolSpec],
    *, confirmed: bool = False, deny_note: str | None = None, user_id: str = "",
) -> ToolRun:
    name = tool_call.get("name") or ""
    tc_id = tool_call.get("id") or ""
    args = dict(tool_call.get("args") or {})
    started = time.monotonic()

    def _run(ok: bool, content: str, status: str, retry_count: int = 0) -> ToolRun:
        return ToolRun(tool_call_id=tc_id, name=name, ok=ok, status=status, retry_count=retry_count,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       tool_message=ToolMessage(content=content, tool_call_id=tc_id,
                                                name=name or "unknown",
                                                status="success" if ok else "error"))

    spec = specs.get(name)

    if spec is None:
        run = _run(False, f"工具执行失败:未知工具 {name}", "失败")
        await _audit(conversation_id, tc_id, name or "unknown", None, args, None,
                     "失败", f"未知工具 {name}", 0, run.duration_ms)
        return run


    try:
        verr = validate_args(spec, args)
    except Exception as e:
        logger.exception("参数校验器异常(多为外部 Server 给的畸形 schema) tool=%s", name)
        run = _run(False, f"工具暂时不可用:参数定义异常({type(e).__name__}),请如实告知用户。", "失败")
        await _audit(conversation_id, tc_id, name, spec, args, None, "失败",
                     f"schema 异常 {type(e).__name__}: {e}"[:500], 0, run.duration_ms)
        return run
    if verr is not None:
        run = _run(False, f"参数校验未通过:{verr}。请修正参数重新调用;缺少的信息请先向用户追问,不要编造。",
                   "校验拦下")
        await _audit(conversation_id, tc_id, name, spec, args, None, "校验拦下", verr, 0, run.duration_ms)
        return run


    if spec.permission == "write" and not confirmed:
        # 确认只来自用户点过的那次操作；未确认时直接拒绝，并明确告诉模型不要自行重试。
        note = deny_note or "该写操作需要用户确认,未确认前拒绝执行。请勿再次发起,除非用户明确要求。"
        run = _run(False, f"{name} 未执行:{note}", "权限拒绝")
        await _audit(conversation_id, tc_id, name, spec, args, None, "权限拒绝",
                     note[:500], 0, run.duration_ms)
        return run

    # 身份与会话字段一律由服务端注入，不采信模型给的同名参数。
    if spec.inject_conversation:
        args["conversation_id"] = conversation_id
    if spec.inject_user_id:
        args["user_id"] = user_id
    if spec.inject_request_id:
        args["idempotency_key"] = f"tool:{tc_id}"
    if spec.source == "mcp":
        # MCP 服务本身不认用户身份，只按订单号/物流单号查；这里先按 user_id 过滤，
        # 避免用户拿别人的单号套出物流与售后信息。
        from sqlalchemy import select
        from app.db import base as db
        from app.db.commerce import Order

        async with db.async_session() as session:
            order_id, tracking_no = args.get("order_id"), args.get("tracking_no")
            if order_id or tracking_no:
                query = select(Order).where(Order.user_id == user_id)
                if order_id:
                    query = query.where(Order.id == order_id)
                if tracking_no:
                    query = query.where(Order.tracking_no == tracking_no)
                if await session.scalar(query) is None:
                    run = _run(False, "没有找到您的订单或物流记录", "权限拒绝")
                    await _audit(conversation_id, tc_id, name, spec, args, None,
                                 "权限拒绝", "订单归属校验失败", 0, run.duration_ms)
                    return run
    # 写操作不重试：重放风险交给幂等键；只有只读工具按配置重试，退避 0.2s×次数。
    if spec.permission == "write":
        retries = 0
    else:
        retries = settings.tool_max_retries if spec.max_retries is None else spec.max_retries
    tool_timeout = _timeout_of(spec)
    attempt = 0
    while True:
        try:
            result = await asyncio.wait_for(spec.tool.ainvoke(args), timeout=tool_timeout)
            content = _format_content(spec, result)
            try:
                structured = json.loads(content)
            except (ValueError, TypeError):
                structured = None
            error = structured.get("error") if isinstance(structured, dict) else None
            status = "失败" if error else "成功"
            run = _run(not bool(error), content, status, attempt)
            await _audit(conversation_id, tc_id, name, spec, args, _summarize(content),
                         status, str(error)[:500] if error else None, attempt, run.duration_ms)
            return run
        except _TRANSIENT as e:
            if attempt < retries:
                attempt += 1
                logger.warning("工具暂时性故障,第 %s 次重试 name=%s err=%s",
                               attempt, name, type(e).__name__)
                await asyncio.sleep(0.2 * attempt)
                continue
            is_timeout = isinstance(e, (asyncio.TimeoutError, TimeoutError))
            status = "超时" if is_timeout else "失败"

            run = _run(False, f"工具暂时不可用:{'执行超时' if is_timeout else type(e).__name__},"
                              "请稍后再试或如实告知用户。", status, attempt)
            await _audit(conversation_id, tc_id, name, spec, args, None, status,
                         type(e).__name__, attempt, run.duration_ms)
            return run
        except Exception as e:
            logger.exception("工具执行失败 name=%s", name)
            run = _run(False, f"工具暂时不可用:{type(e).__name__}。请如实告知用户,不要编造结果。",
                       "失败", attempt)
            await _audit(conversation_id, tc_id, name, spec, args, None, "失败",
                         f"{type(e).__name__}: {e}"[:500], attempt, run.duration_ms)
            return run
