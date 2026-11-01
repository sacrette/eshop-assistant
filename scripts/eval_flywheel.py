import argparse
import asyncio
import json
import pathlib
import sys

from pydantic import BaseModel, Field

from app.core import llm
from app.core.llm import get_chat_model
from app.core.prompts import FAITHFULNESS_PROMPT, RAG_ANSWER_PROMPT
from app.db import repository
from scripts.eval_rag import (
    GRADED_BUCKETS,
    RECALL_K,
    _format_evidence,
    _load,
    _mean,
    _ranks_per_group,
    _recall_at,
    _refusal_one,
    _retrieve,
    _rr,
    _try,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_OUT = _ROOT / "data/reports/knowledge/eval_trend.txt"
_METRICS = ("recall_at_5", "mrr", "faithfulness", "refusal_rate")
_LINES: list[str] = []


def _log(msg=""):
    print(msg, flush=True)
    _LINES.append(msg)


class _Faith(BaseModel):
    faithful: bool = Field(description="是否忠实于证据")
    reason: str = Field(default="")


async def _gen_faith(s, hits, model, judge):
    evidence = _format_evidence(hits)
    ans = await _try(lambda: (RAG_ANSWER_PROMPT | model).ainvoke(
        {"query": s["query"], "evidence": evidence}), f"gen:{s['id']}")
    if ans is None:
        return None
    text = ans.content if isinstance(ans.content, str) else str(ans.content)
    fa = await _try(lambda: (FAITHFULNESS_PROMPT | judge).ainvoke(
        {"evidence": evidence, "answer": text}), f"faith:{s['id']}")
    return None if fa is None else bool(fa.faithful)


async def run_once() -> dict:
    samples = _load()
    graded = [s for s in samples if s["bucket"] in GRADED_BUCKETS]
    absent = [s for s in samples if s["bucket"] == "D_absent"]

    hits_list = await asyncio.gather(*(_retrieve("hybrid_rerank", s) for s in graded))
    ranks = [_ranks_per_group(h, s) for s, h in zip(graded, hits_list)]
    recall = _mean([_recall_at(r, RECALL_K) for r in ranks])
    mrr = _mean([_rr(r) for r in ranks])

    model = get_chat_model()
    judge = llm.structured(_Faith)
    faiths = await asyncio.gather(*(
        _gen_faith(s, h, model, judge) for s, h in zip(graded, hits_list)))
    faithfulness = _mean([1.0 if f else 0.0 for f in faiths if f is not None])

    refusals = await asyncio.gather(*(_refusal_one(s) for s in absent))
    got = [r["refused"] for r in refusals if isinstance(r, dict) and "refused" in r]
    refusal_rate = sum(got) / len(got) if got else 0.0

    return {"dataset_size": len(samples),
            "metrics": {"recall_at_5": round(recall, 3), "mrr": round(mrr, 3),
                        "faithfulness": round(faithfulness, 3),
                        "refusal_rate": round(refusal_rate, 3)}}


def _trend(runs) -> None:
    _log("\n=== 评估趋势(新在上)===")
    names = list(_METRICS)
    _log(f"{'轮次':>4s} {'时间':14s} {'触发':4s}" + "".join(f"{n:>18s}" for n in names))
    for i, r in enumerate(runs):
        prev = runs[i + 1].metrics if i + 1 < len(runs) else None
        row = f"#{r.id:>3d} {r.created_at:%m-%d %H:%M}  {r.triggered_by:4s}"
        for n in names:
            v = r.metrics.get(n)
            cell = f"{v:.3f}" if v is not None else "—"
            if prev and v is not None and prev.get(n) is not None:
                d = v - prev[n]
                cell += " ↑" if d > 0.005 else (" ⚠↓" if d < -0.005 else " →")
            row += f"{cell:>18s}"
        _log(row)
    if len(runs) > 1:
        latest, older = runs[0].metrics, runs[1].metrics
        drops = [n for n in names if latest.get(n, 0) < older.get(n, 0) - 0.005]
        _log(f"\n⚠ 下滑指标:{', '.join(drops)}" if drops else "\n所有指标持平或上涨。")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--triggered-by", default="手动", choices=["手动", "定时"])
    args = ap.parse_args()

    _log(f"=== 知识补全评估流水线(触发:{args.triggered_by})===")
    result = await run_once()
    m = result["metrics"]
    _log(f"本轮:Recall@5={m['recall_at_5']:.3f} MRR={m['mrr']:.3f} "
         f"Faithfulness={m['faithfulness']:.3f} 拒答率={m['refusal_rate']:.3f}")
    await repository.insert_eval_run(args.triggered_by, result["dataset_size"], m)
    runs = await repository.list_eval_runs(limit=10)
    _trend(runs)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
    _log(f"\n趋势报告已落 {_OUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
