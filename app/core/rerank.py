import asyncio
import re

import httpx

from app.config import settings

_VERSION_SEG = re.compile(r"/v\d+$")


def _rerank_url() -> str:
    base = settings.rerank_base_url.rstrip("/")
    if not _VERSION_SEG.search(base):
        base += "/v1"
    return base + "/rerank"


_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRIES = 3
_BACKOFF = 1.5


async def _post(url, json, headers, timeout):
    last: httpx.Response | None = None
    last_exc: Exception | None = None
    for i in range(_RETRIES + 1):
        try:
            async with httpx.AsyncClient() as c:
                resp = await c.post(url, json=json, headers=headers, timeout=timeout)
        except httpx.TransportError as e:


            last_exc = e
            if i < _RETRIES:
                await asyncio.sleep(_BACKOFF * (2 ** i))
                continue
            raise
        if resp.status_code not in _RETRY_STATUS:
            return resp
        last = resp
        if i < _RETRIES:
            await asyncio.sleep(_BACKOFF * (2 ** i))
    if last is None and last_exc is not None:
        raise last_exc
    return last


async def rerank(query: str, docs: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    if not docs:
        return []
    payload = {"model": settings.rerank_model, "query": query, "documents": docs,
               "top_n": top_n or len(docs)}
    resp = await _post(_rerank_url(), payload,
                       {"Authorization": f"Bearer {settings.rerank_api_key}"}, 60)
    resp.raise_for_status()
    results = resp.json()["results"]
    ranked = sorted(((r["index"], float(r["relevance_score"])) for r in results),
                    key=lambda x: x[1], reverse=True)
    return ranked[:top_n] if top_n else ranked
