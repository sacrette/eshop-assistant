import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import settings
from app.core.observability import get_langsmith

OUT = Path(__file__).resolve().parents[1] / "data/reports/usage"


def collect(client, days: int) -> dict:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    buckets = defaultdict(lambda: {"tokens": 0, "count": 0})
    for run in client.list_runs(project_name=settings.langsmith_project, is_root=True, start_time=start):
        outputs = run.outputs or {}
        metadata = (run.extra or {}).get("metadata", {})
        intent = outputs.get("intent") or metadata.get("intent") or "未分类"
        buckets[intent]["tokens"] += run.total_tokens or 0
        buckets[intent]["count"] += 1
    total = sum(v["tokens"] for v in buckets.values())
    rows = [{"intent": intent, **v, "avg_tokens": v["tokens"] // max(v["count"], 1),
             "share": round(v["tokens"] / max(total, 1), 4)} for intent, v in buckets.items()]
    rows.sort(key=lambda r: r["tokens"], reverse=True)
    return {"meta": {"source": "LangSmith", "project": settings.langsmith_project,
                     "days": days, "generated_at": datetime.now(timezone.utc).isoformat()},
            "rows": rows, "total_tokens": total, "total_requests": sum(v["count"] for v in buckets.values())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    client = get_langsmith()
    if client is None:
        print("LangSmith 未启用，请配置 LANGSMITH_TRACING 和 LANGSMITH_API_KEY。")
        return 1
    report = collect(client, max(1, args.days))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cost_by_intent.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
