import logging

from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI
from pydantic import PrivateAttr

from app.config import settings

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _diff_usage(cur: dict, prev: dict) -> dict:
    out: dict = {}
    for k, v in cur.items():
        p = prev.get(k)
        if isinstance(v, dict):
            out[k] = _diff_usage(v, p if isinstance(p, dict) else {})
        elif isinstance(v, (int, float)):
            out[k] = max(0, v - (p if isinstance(p, (int, float)) else 0))
        else:
            out[k] = v
    return out


class _CumulativeUsageChatOpenAI(ChatOpenAI):

    _prev_usage: dict = PrivateAttr(default_factory=dict)

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        usage = chunk.get("usage") if isinstance(chunk, dict) else None
        if usage:
            prev = self._prev_usage


            if any(isinstance(v, (int, float)) and v < prev.get(k, 0)
                   for k, v in usage.items() if not isinstance(v, dict)):
                prev = {}
            chunk = {**chunk, "usage": _diff_usage(usage, prev)}
            self._prev_usage = usage
        return super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info)


def get_chat_model(streaming: bool = False, model: str | None = None,
                   temperature: float | None = None) -> ChatOpenAI:
    return _CumulativeUsageChatOpenAI(
        model=model or settings.chat_model,
        base_url=settings.chat_base_url,
        api_key=settings.chat_api_key,
        streaming=streaming,
        stream_usage=True,
        temperature=0.3 if temperature is None else temperature,
        **_thinking_kwargs(),
    )


def _thinking_kwargs() -> dict:
    kwargs: dict = {}
    extra: dict = {}
    if settings.chat_thinking:
        extra["thinking"] = {"type": settings.chat_thinking}
    if settings.chat_reasoning_split:


        extra["reasoning_split"] = settings.chat_reasoning_split.strip().lower() in _TRUTHY
    if extra:
        kwargs["extra_body"] = extra
    if settings.chat_reasoning_effort:
        kwargs["reasoning_effort"] = settings.chat_reasoning_effort
    return kwargs


_NO_STREAM_TOOLCALL_FAMILIES: tuple[str, ...] = ("minimax",)


def needs_non_streaming_tools(model: str | None = None) -> bool:
    name = (model or settings.chat_model or "").lower()
    return any(f in name for f in _NO_STREAM_TOOLCALL_FAMILIES)


def structured(schema, *, model: str | None = None, streaming: bool = True,
               temperature: float | None = None):
    from langchain_core.runnables import RunnableLambda

    name = (model or settings.chat_model or "").lower()
    if needs_non_streaming_tools(model):
        streaming = False
    m = get_chat_model(streaming=streaming, model=model, temperature=temperature)
    fc = m.with_structured_output(schema, method="function_calling")

    def _log(attempt: int, why: str) -> None:

        logger.warning("%s 经 %s 的 function calling 第 %s 次没成(%s),%s",
                       name, settings.chat_base_url, attempt, why,
                       "原样重试一次" if attempt == 1 else "抛给调用点")

    def _no_tool_calls() -> OutputParserException:
        return OutputParserException(
            f"{name} 经 {settings.chat_base_url} 连着两次都没返回 tool_calls")

    def _run(x):
        for attempt in (1, 2):
            try:
                r = fc.invoke(x)
            except Exception as e:
                _log(attempt, type(e).__name__)
                if attempt == 2:
                    raise
                continue
            if r is not None:
                return r
            _log(attempt, "响应里没有 tool_calls")
        raise _no_tool_calls()

    async def _arun(x):
        for attempt in (1, 2):
            try:
                r = await fc.ainvoke(x)
            except Exception as e:
                _log(attempt, type(e).__name__)
                if attempt == 2:
                    raise
                continue
            if r is not None:
                return r
            _log(attempt, "响应里没有 tool_calls")
        raise _no_tool_calls()

    return RunnableLambda(_run, afunc=_arun)
