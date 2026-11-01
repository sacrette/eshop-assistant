import asyncio
import sys

from app.db import repository
from app.kb import documents
from app.kb.sources import KB_DIR, SOURCE_TYPES


def _norm(s: str) -> str:
    return "\n".join(line.rstrip() for line in (s or "").strip().splitlines())


async def main() -> int:
    in_db = await repository.list_chunks_by_content_types(set(SOURCE_TYPES.values()))


    by_path: dict[str, list] = {}
    for r in in_db:
        by_path.setdefault(r.section_path, []).append(r)
    changed = added = 0
    used: dict[str, int] = {}

    for fname, ctype in SOURCE_TYPES.items():
        md = (KB_DIR / fname).read_text(encoding="utf-8")
        for c in documents.build_chunks(md, content_type=ctype):
            i = used.get(c.section_path, 0)
            used[c.section_path] = i + 1
            rows = by_path.get(c.section_path) or []
            row = rows[i] if i < len(rows) else None
            if row is None:
                print(f"  + 文件里有、库里没有(本脚本不插,走 kb-build / 录入页):"
                      f"{c.section_path} 第 {i + 1} 块")
                added += 1
                continue
            if _norm(row.answer) == _norm(c.answer) and _norm(row.questions) == _norm(c.questions):
                continue
            await repository.repend_chunk_text(row.id, c.questions, c.answer)
            print(f"  ~ 正文已更新(id={row.id}):{c.section_path}")
            changed += 1

    for path, rows in by_path.items():
        for row in rows[used.get(path, 0):]:
            print(f"  ! 库里有、文件里没有(不动它,可能是飞轮写回的):id={row.id} {path}")

    pending = await repository.count_chunks_by_status("pending")
    print(f"\n改动 {changed} 块 · 新小节 {added} 个 · 当前 pending {pending} 块")
    if pending:
        print("下一步:make kb-vectorize(把 pending 的重嵌进 Milvus)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
