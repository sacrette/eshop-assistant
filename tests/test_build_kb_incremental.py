from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import build_kb


@pytest.mark.asyncio
async def test_existing_curated_faq_does_not_skip_missing_documents(monkeypatch, tmp_path):
    (tmp_path / "policy.md").write_text("# 退货政策\n\n## 条件\n\n签收七天内可申请。", encoding="utf-8")
    monkeypatch.setattr(build_kb, "KB_DIR", tmp_path)
    monkeypatch.setattr(build_kb, "DOCS", {"policy.md": "policy"})
    existing = [SimpleNamespace(category="其他", questions="有猫砂吗", answer="有",
                                section_path="审核补全", content_type="policy")]
    monkeypatch.setattr(build_kb.repository, "count_chunks_by_content_types", AsyncMock(return_value=1))
    monkeypatch.setattr(build_kb.repository, "list_chunks_by_content_types", AsyncMock(return_value=existing))
    write = AsyncMock(return_value=[2])
    monkeypatch.setattr(build_kb.dualwrite, "write_pending", write)
    await build_kb.main()
    write.assert_awaited_once()
    chunks = write.await_args.args[0]
    assert chunks[0].answer == "签收七天内可申请。"
    existing.extend(SimpleNamespace(category=c.category, questions=c.questions, answer=c.answer,
        section_path=c.section_path, content_type=c.content_type) for c in chunks)
    write.reset_mock()
    await build_kb.main()
    write.assert_not_awaited()
