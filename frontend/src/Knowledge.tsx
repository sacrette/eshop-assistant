import { BookOpen, Check, RefreshCw, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, post } from './api'
import type { PoolQuestion, Review } from './types'
import { Empty, errorText, time } from './ui'

const sources: Record<string, string> = {
  retrieval_low_conf: '检索证据不足',
  self_check: '证据自评未通过',
  user_feedback: '用户反馈未解决',
}

export default function Knowledge() {
  const [items, setItems] = useState<Review[]>([])
  const [pool, setPool] = useState<PoolQuestion[]>([])
  const [selectedPool, setSelectedPool] = useState<PoolQuestion | null>(null)
  const [selected, setSelected] = useState<Review | null>(null)
  const [answer, setAnswer] = useState('')
  const [filter, setFilter] = useState('问题池')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  async function refresh() {
    const [result, raw] = await Promise.all([
      api<{ items: Review[] }>('/api/review/queue'),
      api<{ items: PoolQuestion[] }>('/api/review/pool'),
    ])
    setItems(result.items)
    setPool(raw.items)
  }
  useEffect(() => {
    refresh().catch((e) => setError(errorText(e)))
  }, [])
  async function select(item: Review) {
    setError('')
    setNotice('')
    setSelected(null)
    try {
      const detail = await api<Review>(`/api/review/${item.id}`)
      setSelected(detail)
      setAnswer(
        detail.approved_answer || detail.publication?.answer || detail.ai_suggested_answer || '',
      )
    } catch (e) {
      setError(errorText(e))
    }
  }
  async function decide(approve: boolean) {
    if (!selected || busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await post(
        `/api/review/${selected.id}/${approve ? 'approve' : 'reject'}`,
        approve ? { approved_answer: answer } : {},
      )
      setNotice(approve ? '知识已审核发布，索引已完成。' : '问题已驳回。')
      setSelected({
        ...selected,
        review_status: approve ? '通过' : '驳回',
        approved_answer: approve ? answer : null,
      })
      await refresh()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  async function processPool() {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const r = await post<{ processed: number; skipped: number }>('/api/review/process-pool', {})
      setNotice(
        `已整理 ${r.processed} 条，暂未处理 ${r.skipped} 条。未处理的问题保留在问题池，可重试。`,
      )
      await refresh()
      if (r.processed > 0) {
        setSelectedPool(null)
        setSelected(null)
        setFilter('待审')
      }
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const visible = items.filter(
    (item) => item.review_status === filter && item.normalized_question.includes(search),
  )
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <h1>把未解决的问题，变成下一次的答案。</h1>
          <p>核实问题来源与答案内容，审核通过并完成索引后供后续咨询使用。</p>
        </div>
        <div className="button-group">
          <button
            className="icon-button"
            aria-label="刷新知识队列"
            onClick={() => refresh().catch((e) => setError(errorText(e)))}
          >
            <RefreshCw size={17} />
          </button>
          <button className="button secondary" disabled={busy} onClick={() => void processPool()}>
            整理新问题
          </button>
        </div>
      </div>
      <div className="workspace-tabs">
        {['问题池', '待审', '通过', '驳回'].map((status) => (
          <button
            className={filter === status ? 'selected' : ''}
            key={status}
            onClick={() => {
              setFilter(status)
              setSelected(null)
              setSelectedPool(null)
            }}
          >
            {status === '问题池'
              ? '待整理问题池'
              : status === '通过'
                ? '已发布'
                : status === '驳回'
                  ? '已驳回'
                  : '待审核'}
            <span>
              {status === '问题池'
                ? pool.length
                : items.filter((i) => i.review_status === status).length}
            </span>
          </button>
        ))}
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      <div className="case-layout knowledge-layout">
        <section className="queue-panel">
          <div className="queue-controls">
            <div className="search-input">
              <Search size={16} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索问题"
                aria-label="搜索知识问题"
              />
            </div>
          </div>
          {filter === '问题池' &&
            pool
              .filter((item) => item.raw_question.includes(search))
              .map((item) => (
                <button
                  className={`queue-item ${selectedPool?.id === item.id ? 'active' : ''}`}
                  key={item.id}
                  disabled={busy}
                  onClick={() => setSelectedPool(item)}
                >
                  <span className="quiet-label">{sources[item.source] || item.source}</span>
                  <h3>{item.raw_question}</h3>
                  <footer>
                    {time(item.created_at)}
                    <BookOpen size={16} />
                  </footer>
                </button>
              ))}
          {(filter === '问题池'
            ? pool.filter((item) => item.raw_question.includes(search)).length === 0
            : visible.length === 0) && (
            <Empty
              title="当前队列为空"
              description={
                filter === '问题池'
                  ? '暂无匹配的待整理问题。拒答和用户未解决反馈会在此显示。'
                  : '点击「整理新问题」，将问题池中的咨询归并到审核队列。'
              }
            />
          )}
          {filter !== '问题池' &&
            visible.map((item) => (
              <button
                className={`queue-item ${selected?.id === item.id ? 'active' : ''}`}
                key={item.id}
                onClick={() => void select(item)}
                disabled={busy}
              >
                <span className="quiet-label">出现 {item.occurrence_count} 次</span>
                <h3>{item.normalized_question}</h3>
                <footer>
                  {time(item.created_at)}
                  <BookOpen size={16} />
                </footer>
              </button>
            ))}
        </section>
        <section className="case-detail">
          {filter === '问题池' && selectedPool ? (
            <>
              <div className="detail-header">
                <span className="quiet-label">待整理 · 问题 #{selectedPool.id}</span>
                <h2>{selectedPool.raw_question}</h2>
                <p>
                  {sources[selectedPool.source] || selectedPool.source} ·{' '}
                  {time(selectedPool.created_at)}
                </p>
              </div>
              <div className="detail-section">
                <h3>收集原因</h3>
                <p className="source-question">{selectedPool.reason || '暂无详细原因'}</p>
                <p className="editor-hint">
                  来自会话 {selectedPool.conversation_id ?? '未关联'}
                  。点击「整理新问题」后，系统标准化并归并相似问题，再由人工审核答案。列表最多显示
                  200 条待整理记录。
                </p>
              </div>
            </>
          ) : selected ? (
            <>
              <div className="detail-header">
                <span className="quiet-label">知识审核</span>
                <h2>{selected.normalized_question}</h2>
                <p>
                  当前状态：{selected.review_status} · 出现 {selected.occurrence_count} 次
                </p>
              </div>
              <div className="detail-section">
                <h3>问题来源</h3>
                {selected.raws?.map((raw, i) => (
                  <div className="source-question" key={i}>
                    <span>{sources[raw.source] || raw.source}</span>
                    <p>{raw.raw_question}</p>
                    <small>{raw.reason}</small>
                  </div>
                ))}
              </div>
              <div className="detail-section">
                <label>
                  审核答案
                  <textarea
                    className="answer-editor"
                    rows={10}
                    value={answer}
                    maxLength={20000}
                    disabled={selected.review_status !== '待审' || busy}
                    onChange={(e) => setAnswer(e.target.value)}
                    placeholder="依据已核实的商品或政策资料填写答案，删除无法确认的承诺。"
                  />
                </label>
                <p className="editor-hint">AI 建议只供参考，请核实适用条件、金额与时效。</p>
              </div>
              {selected.review_status === '待审' && (
                <div className="case-decision">
                  <div>
                    <button
                      className="button secondary"
                      disabled={busy}
                      onClick={() => void decide(false)}
                    >
                      <X size={16} />
                      驳回
                    </button>
                    <button
                      className="button"
                      disabled={busy || !answer.trim()}
                      onClick={() => void decide(true)}
                    >
                      <Check size={16} />
                      {busy ? '处理中…' : '审核并发布'}
                    </button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <Empty
              title={filter === '问题池' ? '选择一个待整理问题' : '选择一个待审核问题'}
              description={
                filter === '问题池'
                  ? '查看咨询原文、来源和未解决原因，再整理到审核队列。'
                  : '查看真实问题与来源，补充可验证的答案。'
              }
            />
          )}
        </section>
      </div>
    </div>
  )
}
