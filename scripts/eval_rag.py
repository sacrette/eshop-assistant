import asyncio
import json
import pathlib
import sys
from datetime import datetime

from pydantic import BaseModel, Field

from app.config import settings
from app.core import model_guard, retrieval
from app.core import llm
from app.core.llm import get_chat_model
from app.core.prompts import FAITHFULNESS_PROMPT, RAG_ANSWER_PROMPT
from app.kb import milvus_client
from app.tools.builtin import faq

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT_DIR = _ROOT / "data/reports/rag"
_OUT_JSON = _OUT_DIR / "rag_eval.json"
_OUT_TXT = _OUT_DIR / "rag_eval.txt"

STRATEGIES = ["vector", "bm25", "hybrid", "hybrid_rerank"]
GRADED_BUCKETS = ["A_policy", "B_model", "C_colloquial", "E_multi"]

STRATEGY_LABEL = {"vector": "纯向量", "bm25": "纯 BM25", "hybrid": "混合",
                  "hybrid_rerank": "混合 + 重排"}
BUCKET_LABEL = {"A_policy": "政策类", "B_model": "型号类",
                "C_colloquial": "口语类", "E_multi": "跨文档类", "overall": "总体"}
SKIP_GEN = "--skip-gen" in sys.argv
K = 10
RECALL_K = 5

RETR_CONCURRENCY = 5
GEN_CONCURRENCY = 1


CALL_TIMEOUT = 45.0

_retr_sem = asyncio.Semaphore(RETR_CONCURRENCY)
_gen_sem = asyncio.Semaphore(GEN_CONCURRENCY)
_errs: list[str] = []


class _Faith(BaseModel):
    faithful: bool = Field(description="是否忠实于证据")
    reason: str = Field(default="")


class _Cov(BaseModel):
    covered_count: int = Field(description="客服答案正确覆盖的要点个数")


COVERAGE_SYS = """你是答案覆盖度评审员。给定用户问题、标准答案要点清单、客服答案。
数一数客服答案里正确覆盖了几个要点:要点信息在答案中有正确体现才算,遗漏、编造或答错都不算。
只需给出覆盖的要点个数(整数),不要超过要点总数。"""
from langchain_core.prompts import ChatPromptTemplate

COVERAGE_PROMPT = ChatPromptTemplate.from_messages(
    [("system", COVERAGE_SYS),
     ("human", "用户问题:{query}\n\n标准答案要点(共 {n} 个):\n{points}\n\n客服答案:\n{answer}")]
)


_LINES: list[str] = []


def _log(msg=""):
    print(msg, flush=True)
    _LINES.append(msg)


def _load():
    return [json.loads(ln) for ln in open("tests/data/rag_eval.jsonl")]


def _hit_rank(hits, expect_section):
    for i, h in enumerate(hits):
        sp = h.get("section_path", "") or ""
        if any(w in sp for w in expect_section):
            return i + 1
    return 0


def _groups(sample) -> list[list[str]]:
    groups = sample.get("expect_sections_all")
    if groups:
        return [g if isinstance(g, list) else [g] for g in groups]
    return [sample["expect_section"]]


def _ranks_per_group(hits, sample) -> list[int]:
    return [_hit_rank(hits, g) for g in _groups(sample)]


def _recall_at(ranks: list[int], k: int) -> float:
    return _mean([1.0 if 0 < r <= k else 0.0 for r in ranks])


def _rr(ranks: list[int]) -> float:
    return _mean([(1.0 / r if r else 0.0) for r in ranks])


def _norm(s: str) -> str:
    return "".join((s or "").split())


def _evidence_text(hits) -> str:
    return "\n".join(f"{h.get('question', '')}:{h.get('answer', '')}" for h in hits)


def _coverage_mech(points, hits) -> float | None:
    if not points:
        return None
    ev = _norm(_evidence_text(hits))
    return sum(1 for p in points if _norm(p) in ev) / len(points)


def _format_evidence(hits) -> str:
    return "\n".join(f"[{i+1}] {h.get('question', '')}:{h.get('answer', '')}"
                     for i, h in enumerate(hits))


async def _try(factory, label):
    for i in range(2):
        try:
            return await asyncio.wait_for(factory(), CALL_TIMEOUT)
        except Exception as e:
            if i == 0:
                await asyncio.sleep(5.0)
                continue
            _errs.append(f"{label}: {type(e).__name__}")
    return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


async def _retrieve(strat, s):
    async with _retr_sem:
        return await retrieval.search_knowledge(s["query"], strategy=strat, top_k=K)


async def _deterministic(samples):
    graded = [s for s in samples if s["bucket"] in GRADED_BUCKETS]
    retrieval_out, coverage_out, HITS = {}, {}, {}
    _log("=== 段1 检索:四策略 × 分桶 Recall@%d / MRR ===" % RECALL_K)
    header = f"{'strategy':16s}" + \
        "".join(
            f"{b.split('_')[0]:>16s}" for b in GRADED_BUCKETS) + f"{'OVERALL':>16s}"
    _log(header)
    for strat in STRATEGIES:
        hits_list = await asyncio.gather(*(_retrieve(strat, s) for s in graded))
        HITS[strat] = {s["id"]: h for s, h in zip(graded, hits_list)}
        by_bucket, cov_bucket = {}, {}
        row = f"{strat:16s}"
        all_rec, all_rr, all_cov = [], [], []
        for b in GRADED_BUCKETS:
            idx = [i for i, s in enumerate(graded) if s["bucket"] == b]
            ranks = [_ranks_per_group(hits_list[i], graded[i]) for i in idx]
            covs = [_coverage_mech(
                graded[i]["expect_points"], hits_list[i]) for i in idx]
            rec = _mean([_recall_at(r, RECALL_K) for r in ranks])
            mrr = _mean([_rr(r) for r in ranks])
            by_bucket[b] = {"recall": round(rec, 3), "mrr": round(mrr, 3)}
            cov_bucket[b] = round(_mean(covs), 3)
            all_rec += [_recall_at(r, RECALL_K) for r in ranks]
            all_rr += [_rr(r) for r in ranks]
            all_cov += [c for c in covs if c is not None]
            row += f"  R{rec:.2f}/M{mrr:.2f}".rjust(16)
        by_bucket["overall"] = {"recall": round(
            _mean(all_rec), 3), "mrr": round(_mean(all_rr), 3)}
        cov_bucket["overall"] = round(_mean(all_cov), 3)
        retrieval_out[strat] = by_bucket
        coverage_out[strat] = cov_bucket
        row += f"  R{_mean(all_rec):.2f}/M{_mean(all_rr):.2f}".rjust(16)
        _log(row)

    _log("\n=== 段2 证据覆盖度(Top-%d 证据盖住标准要点的比例,机械匹配·确定性)===" % K)
    header = f"{'strategy':16s}" + \
        "".join(
            f"{b.split('_')[0]:>12s}" for b in GRADED_BUCKETS) + f"{'OVERALL':>12s}"
    _log(header)
    for strat in STRATEGIES:
        row = f"{strat:16s}" + \
            "".join(f"{coverage_out[strat][b]:>12.2f}" for b in GRADED_BUCKETS)
        row += f"{coverage_out[strat]['overall']:>12.2f}"
        _log(row)
    return retrieval_out, coverage_out, HITS


async def _gen_one(strat, s, HITS, model, cov_judge, faith_judge,
                   cov_prompt, faith_prompt):
    hits = HITS[strat][s["id"]]
    evidence = _format_evidence(hits)
    async with _gen_sem:
        ans = await _try(
            lambda: (RAG_ANSWER_PROMPT | model).ainvoke(
                {"query": s["query"], "evidence": evidence}),
            f"gen:{strat}:{s['id']}")
        if ans is None:
            return {"strat": strat, "bucket": s["bucket"], "coverage": None,
                    "faithful": None, "guard_hits": []}
        text = ans.content if isinstance(
            ans.content, str) else str(ans.content)


        guard_hits = []
        bad = model_guard.unsupported_models(text, evidence)
        if bad:
            guard_hits.append(
                {"id": s["id"], "strat": strat, "models": bad, "fixed": False})
            retry = await _try(
                lambda: (RAG_ANSWER_PROMPT | model).ainvoke(
                    {"query": s["query"],
                     "evidence": evidence + "\n\n" + model_guard.repair_hint(bad)}),
                f"guard-retry:{strat}:{s['id']}")
            if retry is not None:
                fixed_text = retry.content if isinstance(
                    retry.content, str) else str(retry.content)
                if not model_guard.unsupported_models(fixed_text, evidence):
                    text = fixed_text
                    guard_hits[-1]["fixed"] = True
        cov = await _try(
            lambda: (cov_prompt | cov_judge).ainvoke(
                {"query": s["query"], "n": len(s["expect_points"]),
                 "points": "\n".join(f"{i+1}. {p}" for i, p in enumerate(s["expect_points"])),
                 "answer": text}),
            f"cov:{strat}:{s['id']}")
        coverage = None
        if cov is not None and s["expect_points"]:
            coverage = min(cov.covered_count, len(
                s["expect_points"])) / len(s["expect_points"])
        faithful = None
        faith_detail = None
        if strat == "hybrid_rerank":
            fa = await _try(
                lambda: (faith_prompt | faith_judge).ainvoke(
                    {"evidence": evidence, "answer": text}),
                f"faith:{s['id']}")
            if fa is not None:
                faithful = bool(fa.faithful)
                if not faithful:


                    faith_detail = {"id": s["id"], "bucket": s["bucket"],
                                    "query": s["query"], "answer": text, "reason": fa.reason,
                                    "citations": [
                                        {"n": i + 1, "chunk_id": h.get("id"),
                                         "section_path": h.get("section_path", ""),
                                         "question": h.get("question", ""),
                                         "answer": h.get("answer", "")}
                                        for i, h in enumerate(hits)]}
    return {"strat": strat, "bucket": s["bucket"], "coverage": coverage,
            "faithful": faithful, "faith_detail": faith_detail,
            "guard_hits": guard_hits}


async def _refusal_one(s):
    async with _gen_sem:
        out = await _try(lambda: faq.query_faq.ainvoke({"keyword": s["query"]}),
                         f"refuse:{s['id']}")
    if out is None:
        return None
    refused = not out.get("sufficient")
    detail = None
    if not refused:
        cites = out.get("citations") or []
        top = cites[0] if cites else {}
        detail = {"id": s["id"], "query": s["query"],
                  "section_path": top.get("section_path", ""),
                  "evidence": f"{top.get('question', '')}:{top.get('answer', '')}"[:220]}
    return {"refused": refused, "detail": detail}


async def _generation(samples, HITS):
    graded = [s for s in samples if s["bucket"] in GRADED_BUCKETS]
    absent = [s for s in samples if s["bucket"] == "D_absent"]
    model = get_chat_model()


    cov_judge = llm.structured(_Cov, temperature=0)
    faith_judge = llm.structured(_Faith, temperature=0)
    cov_prompt, faith_prompt = COVERAGE_PROMPT, FAITHFULNESS_PROMPT

    _log("\n=== 段3 生成:四策略答案覆盖度(glm 判分)+ Faithfulness + D 桶拒答 ===")
    tasks = [_gen_one(strat, s, HITS, model, cov_judge, faith_judge, cov_prompt, faith_prompt)
             for strat in STRATEGIES for s in graded]
    tasks += [_refusal_one(s) for s in absent]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    n_gen = len(STRATEGIES) * len(graded)
    gen_results = [r for r in results[:n_gen] if isinstance(r, dict)]
    raw_refusals = results[n_gen:]
    refusals = [r for r in raw_refusals if isinstance(
        r, dict) and "refused" in r]
    refusal_skipped = [s["id"] for s, r in zip(absent, raw_refusals)
                       if not (isinstance(r, dict) and "refused" in r)]


    if not refusals and not any(r["coverage"] is not None or r["faithful"] is not None
                                for r in gen_results):
        raise RuntimeError(f"生成段 {len(_errs)} 次调用全部失败(上游不可用),不落零分")


    answer_cov = {}
    _log("\n-- 答案覆盖度(生成答案盖住标准要点的比例)--")
    header = f"{'strategy':16s}" + \
        "".join(
            f"{b.split('_')[0]:>12s}" for b in GRADED_BUCKETS) + f"{'OVERALL':>12s}"
    _log(header)
    for strat in STRATEGIES:
        by = {}
        allc = []
        for b in GRADED_BUCKETS:
            cs = [r["coverage"] for r in gen_results if r["strat"] ==
                  strat and r["bucket"] == b and r["coverage"] is not None]

            by[b] = round(_mean(cs), 3) if cs else None
            allc += cs
        by["overall"] = round(_mean(allc), 3) if allc else None
        answer_cov[strat] = by
        def fmt(v): return ("     未评上" if v is None else f"{v:>12.2f}")
        _log(f"{strat:16s}" + "".join(fmt(by[b])
             for b in GRADED_BUCKETS) + fmt(by["overall"]))


    faithfulness = {}
    _log("\n-- Faithfulness(hybrid_rerank 线上管线,答案不编造)--")
    for b in GRADED_BUCKETS:
        fs = [r["faithful"] for r in gen_results if r["strat"] ==
              "hybrid_rerank" and r["bucket"] == b and r["faithful"] is not None]
        faithfulness[b] = {"v": round(
            _mean(fs), 3) if fs else None, "answered": len(fs)}
        shown = "未评上" if not fs else f"{faithfulness[b]['v']:.3f}"
        _log(f"{b:14s} faithfulness={shown} (评 {len(fs)} 题)")


    faith_cases = [r["faith_detail"]
                   for r in gen_results if r.get("faith_detail")]
    faith_cases.sort(key=lambda c: c["id"])
    if faith_cases:
        _log(
            f"\n-- 被判不忠实(编造)个案:{len(faith_cases)} 例 → {', '.join(c['id'] for c in faith_cases)} --")
    else:
        _log("\n-- 被判不忠实(编造)个案:0 例 --")


    correct = sum(1 for r in refusals if r["refused"])

    rate = (correct / len(refusals)) if refusals else None
    shown_rate = "未评上" if rate is None else f"{rate:.3f}"
    _log(
        f"\n-- D 桶拒答率(线上管线)= {shown_rate}({correct}/{len(refusals)} 正确拒答;评 {len(refusals)}/{len(absent)} 题)--")
    miss_cases = [r["detail"] for r in refusals if r["detail"]]
    miss_cases.sort(key=lambda c: c["id"])
    if miss_cases:
        for c in miss_cases:
            _log(
                f"   该拒没拒:{c['id']} 「{c['query']}」← 被当成答案的证据:{c['section_path']}")
    else:
        _log("   该拒没拒:0 例")
    if refusal_skipped:
        _log(f"   未评上(调用失败/超时):{', '.join(refusal_skipped)}")


    guard_hits = [h for r in gen_results for h in r.get("guard_hits", [])]
    guard = {"hits": len(guard_hits), "fixed": sum(1 for h in guard_hits if h["fixed"]),
             "cases": sorted(guard_hits, key=lambda h: (h["id"], h["strat"]))}
    _log(f"\n-- 型号机械闸:命中 {guard['hits']} 次,重写救回 {guard['fixed']} 次 --")
    for h in guard["cases"]:
        _log(f"   {h['id']}({h['strat']}) 证据里没有的型号:{'、'.join(h['models'])}"
             f" → {'重写后干净' if h['fixed'] else '重写后仍不干净'}")

    return {"answer_coverage": answer_cov, "faithfulness": faithfulness,
            "faithfulness_cases": faith_cases, "model_guard": guard,
            "refusal": {"rate": (round(rate, 3) if rate is not None else None),
                        "total": len(refusals), "correct": correct,
                        "cases": miss_cases, "skipped_ids": refusal_skipped},
            "skipped": len(_errs)}


async def _kb_chunks():
    try:
        def work():
            c = milvus_client.get_client()
            milvus_client.ensure_collection(c)
            return milvus_client.count(c)
        return await milvus_client.acall(work)
    except Exception:
        return "—"


def _labeled(data, pick=None):
    return {STRATEGY_LABEL[s]: {BUCKET_LABEL[b]: (pick((data[s].get(b) or {})) if pick
                                                  else (data[s] or {}).get(b))
                                for b in GRADED_BUCKETS + ["overall"]}
            for s in STRATEGIES}


def _write_report(retrieval_data, coverage_data, generation_data, meta):
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    _OUT_TXT.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
    report = {"meta": meta, "retrieval": retrieval_data,
              "evidence_coverage": coverage_data, "generation": generation_data}

    _OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")


async def main():
    samples = _load()
    import collections as _c
    per = _c.Counter(s["bucket"] for s in samples)
    _log(f"评估集:{len(samples)} 题(" + "、".join(
        f"{BUCKET_LABEL.get(b, b)} {n}" for b, n in per.most_common()) + f"),策略 {STRATEGIES}")
    _log(
        f"检索并发 {RETR_CONCURRENCY} · 生成并发 {GEN_CONCURRENCY} · 单调用超时 {CALL_TIMEOUT:.0f}s\n")
    retrieval_data, coverage_data, HITS = await _deterministic(samples)
    generation_data = None
    if SKIP_GEN:
        _log("\n[生成段跳过] --skip-gen:本轮只跑确定性两段,报告标注生成段未完成。")
    else:
        try:
            generation_data = await _generation(samples, HITS)
        except Exception as e:
            _log(f"\n[生成段未完成] {type(e).__name__}: {str(e)[:140]}")
            _log("检索段与证据覆盖度已完成;报告会标注生成段未完成,上游恢复后重跑补全。")
    if _errs:
        _log(f"\n注:生成段有 {len(_errs)} 次 glm 调用超时/失败被跳过(上游不稳),已按可用样本计。")
    meta = {"n_samples": len(samples), "kb_chunks": await _kb_chunks(),
            "recall_k": RECALL_K, "retrieve_k": K,
            "concurrency": GEN_CONCURRENCY, "chat_model": settings.chat_model,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}

    _write_report(retrieval_data, coverage_data, generation_data, meta)
    _log(f"\n已生成:{_OUT_JSON.relative_to(_ROOT)} · {_OUT_TXT.relative_to(_ROOT)}")
    _log("完成。" if generation_data is not None else "完成(仅检索段+证据覆盖度;生成段待上游恢复重跑)。")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
