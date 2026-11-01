from app.kb import chunking, documents
from app.kb.sources import KB_DIR, SOURCE_TYPES as DOCS


def _preview(text: str, n: int = 46) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n] + "…"


def main() -> None:
    print("=== 离线建库材料清单 ===")
    print("文档(结构化切块 → knowledge_chunks):")
    for fname, ctype in DOCS.items():
        p = KB_DIR / fname
        raw = p.read_text(encoding="utf-8")
        print(f"  data/kb/{fname:<24} [{ctype:<6}] {len(raw):>4} 字符 / {raw.count(chr(10)) + 1} 行")
    print("\n=== 切块预览(dry-run,不写库)===")
    tally: dict[str, int] = {}
    key_total = 0
    table_notes: list[str] = []
    for fname, ctype in DOCS.items():
        md = (KB_DIR / fname).read_text(encoding="utf-8")
        chunks = documents.build_chunks(md, content_type=ctype)
        tally[ctype] = tally.get(ctype, 0) + len(chunks)

        by_path: dict[str, list[documents.Chunk]] = {}
        for c in chunks:
            by_path.setdefault(c.section_path, []).append(c)
        print(f"\n▼ {fname} [{ctype}]  →  {len(chunks)} 块")
        for path, group in by_path.items():
            multi = f"  (该节切成 {len(group)} 块)" if len(group) > 1 else ""
            print(f"  ┌ 节:{path}{multi}")
            for j, c in enumerate(group, 1):
                key_total += c.is_key_clause
                flag = " ★关键条款" if c.is_key_clause else ""
                seq = f"{j}/{len(group)}" if len(group) > 1 else "-"
                is_tbl = chunking.is_table_block(c.answer)
                kind = "表格块" if is_tbl else "文本块"
                print(f"  │ [{kind} {seq}]{flag}  Q(questions)={c.questions}  category={c.category}")
                print(f"  │   A({len(c.answer)}字): {_preview(c.answer)}")
                if is_tbl and len(group) > 1:
                    header = c.answer.strip().splitlines()[0]
                    table_notes.append(f"{fname}「{path.split(' / ')[-1]}」块{seq} 复制表头: {header.strip()}")
    print("\n=== 汇总 ===")
    print(f"总块数 {sum(tally.values())};类型分布 " + " ".join(f"{k}={v}" for k, v in tally.items()))
    print(f"关键条款(is_key_clause=1)共 {key_total} 块(命中 运费/邮费/退款/保修 等词)")
    if table_notes:
        print("表格按行拆(表头复制)已触发:")
        for n in table_notes:
            print(f"  · {n}")
    print("句子边界 overlap:仅当单节 > chunk_size(400字)被 recursive_split 成多块时触发;"
          "当前各节均较短未触发,该逻辑由 tests/test_chunking.py 锁定。")


if __name__ == "__main__":
    main()
