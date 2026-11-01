import re

MODEL_RE = re.compile(r"MH-[A-Za-z]{1,4}\d{1,4}")


def models_in(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in MODEL_RE.findall(text or ""):
        seen.setdefault(m, None)
    return list(seen)


def unsupported_models(answer: str, evidence: str) -> list[str]:
    allowed = set(models_in(evidence))
    return [m for m in models_in(answer) if m not in allowed]


def repair_hint(bad: list[str]) -> str:
    return (
        "上一版回答里这些型号在给你的证据里找不到:" + "、".join(bad) + "。"
        "请重写回答:型号必须逐字复制证据里出现过的型号串,证据里没有的型号一个都不要写,"
        "拿不准就不提型号。其余内容与引用编号保持不变。"
    )
