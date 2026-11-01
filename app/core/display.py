from datetime import datetime


def logistics_trace(events: list[dict] | None) -> list[dict] | None:
    """展示副本使用分钟精度，保留存储中的原始物流时间。"""
    if events is None:
        return None
    result = []
    for event in events:
        item = dict(event)
        stamp = item.get("time")
        if isinstance(stamp, str):
            try:
                item["time"] = datetime.fromisoformat(stamp).strftime("%m月%d日 %H:%M")
            except ValueError:
                pass
        result.append(item)
    return result
