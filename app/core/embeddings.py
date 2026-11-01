from openai import AsyncOpenAI

from app.config import settings

_CLIENT: AsyncOpenAI | None = None


def _client() -> AsyncOpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AsyncOpenAI(base_url=settings.embed_base_url, api_key=settings.embed_api_key)
    return _CLIENT


async def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = await _client().embeddings.create(model=settings.embed_model, input=texts)
    return [d.embedding for d in resp.data]


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
