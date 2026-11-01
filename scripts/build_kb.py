import asyncio

from app.db import repository
from app.kb import documents, dualwrite
from app.kb.sources import KB_DIR, SOURCE_TYPES as DOCS


async def main() -> None:

    existing = await repository.count_chunks_by_content_types(set(DOCS.values()))
    if existing:
        print(f"⚠️ 已存在 {existing} 条文档块,跳过以防重复插入。需要更新正文时运行 scripts.kb_repatch")
        return
    total = 0
    for fname, ctype in DOCS.items():
        md = (KB_DIR / fname).read_text(encoding="utf-8")
        chunks = documents.build_chunks(md, content_type=ctype)
        ids = await dualwrite.write_pending(chunks)
        total += len(ids)
        print(f"  {fname}: {len(ids)} 块")
    print(f"✅ 建库(pending):共 {total} 块。下一步:scripts/vectorize_kb.py")


if __name__ == "__main__":
    asyncio.run(main())
