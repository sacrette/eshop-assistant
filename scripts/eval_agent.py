import asyncio
import json

import httpx

BASE = "http://localhost:8000"


SAMPLES = [
    ("订单 1001 的物流到哪了", {"query_logistics"}),
    ("退货政策是什么", {"query_faq"}),
    ("买的鞋子能不能退", {"query_faq"}),
    ("邮费是多少", {"query_faq"}),
    ("iPhone 还有货吗", {"query_product"}),
    ("订单 2002 多少钱", {"query_order"}),
    ("我要投诉,给我登记一下", {"create_ticket"}),
    ("今天天气怎么样", None),
]


def _faq_note(body: dict) -> str:
    faq_calls = [tc for tc in body["tool_calls"] if tc["name"] == "query_faq"]
    faq_results = [tr for tr in body["tool_results"] if tr["name"] == "query_faq"]
    if not faq_calls or not faq_results:
        return ""
    keyword = faq_calls[0]["args"].get("keyword", "")
    hits = json.loads(faq_results[0]["content"]).get("hits", [])
    return f"  [query_faq keyword={keyword!r} 漏召回={'是' if not hits else '否'}]"


async def main() -> None:
    passed = 0
    async with httpx.AsyncClient(timeout=60) as client:
        for msg, expect in SAMPLES:
            r = await client.post(f"{BASE}/api/agent", json={"user_id": "eval", "message": msg})
            body = r.json()
            names = {tc["name"] for tc in body["tool_calls"]}
            ok = (not names) if expect is None else bool(names & expect)
            passed += ok
            print(f"{'✅' if ok else '❌'} {msg!r} -> {names or '(未调用)'} 期望={expect}{_faq_note(body)}")
            print(f"    answer: {body['answer'][:70]}")
    print(f"\n选对工具 {passed}/{len(SAMPLES)}(glm 非确定性,抖动如实重跑记录)")


if __name__ == "__main__":
    asyncio.run(main())
