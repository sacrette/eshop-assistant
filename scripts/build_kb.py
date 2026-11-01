import asyncio
from collections import Counter

from app.db import repository
from app.kb import documents, dualwrite
from app.kb.sources import KB_DIR, SOURCE_TYPES as DOCS


async def main() -> None:

    existing = await repository.list_chunks_by_content_types(set(DOCS.values()))
    # 按章节及块数补缺，审核补全 FAQ 不应阻止基础文档入库。
    # 已有章节正文的修改仍由 kb_repatch 处理，避免混入旧版本重复证据。
    def key(chunk):
        return (chunk.content_type, chunk.section_path, chunk.questions)
    remaining = Counter(key(row) for row in existing)
    total = 0
    for fname, ctype in DOCS.items():
        md = (KB_DIR / fname).read_text(encoding="utf-8")
        chunks = documents.build_chunks(md, content_type=ctype)
        missing = []
        for chunk in chunks:
            k = key(chunk)
            if remaining[k]:
                remaining[k] -= 1
            else:
                missing.append(chunk)
        ids = await dualwrite.write_pending(missing) if missing else []
        total += len(ids)
        print(f"  {fname}: {len(ids)} 块")
    print(f"✅ 建库(pending):共 {total} 块。下一步:scripts/vectorize_kb.py")


if __name__ == "__main__":
    asyncio.run(main())
