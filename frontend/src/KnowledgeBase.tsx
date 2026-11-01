import { Boxes, Check, Database, FileText, Layers, RefreshCw, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api, post } from './api'
import type { KbChunk, KbHit, KbIngest, KbOverview, KbPreview, KbStaging, KbStats } from './types'
import { Empty, errorText, time } from './ui'

const STRATEGIES = [
  { value: 'hybrid_rerank', label: '混合 + 重排' },
  { value: 'hybrid', label: '混合' },
  { value: 'vector', label: '纯向量' },
  { value: 'bm25', label: '纯 BM25' },
]

const STAGING_STATUS: Record<string, string> = {
  extracted: '待整理',
  kept: '可采纳',
  discarded: '已弃用',
  approved: '已采纳',
  rejected: '已驳回',
}

type Tab = 'overview' | 'ingest' | 'search' | 'staging'

function Badge({ tone, children }: { tone?: 'ok' | 'warn'; children: ReactNode }) {
  return <span className={`kb-badge${tone ? ` ${tone}` : ''}`}>{children}</span>
}

function ChunkRow({ chunk }: { chunk: KbChunk }) {
  return (
    <div className="kb-row">
      <header>
        <h4>{chunk.questions || '(无问句)'}</h4>
        <div className="kb-badges">
          {chunk.duplicate && <Badge tone="warn">重复</Badge>}
          {chunk.is_key_clause && <Badge>关键条款</Badge>}
          {chunk.is_table && <Badge>表格</Badge>}
        </div>
      </header>
      <p>{chunk.answer}</p>
      <footer>
        <span>{chunk.section_path || '(无标题层级)'}</span>
        <span>{chunk.category}</span>
        {chunk.chars !== undefined && <span>{chunk.chars} 字</span>}
        {chunk.status && <span>{chunk.status}</span>}
        {chunk.created_at && <span>{time(chunk.created_at)}</span>}
      </footer>
    </div>
  )
}

export default function KnowledgeBase() {
  const [tab, setTab] = useState<Tab>('overview')
  const [overview, setOverview] = useState<KbOverview | null>(null)
  const [staging, setStaging] = useState<KbStaging | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const [source, setSource] = useState('')
  const [text, setText] = useState('')
  const [ctype, setCtype] = useState('faq')
  const [preview, setPreview] = useState<KbPreview | null>(null)
  const [previewFromFile, setPreviewFromFile] = useState(false)

  const [query, setQuery] = useState('')
  const [strategy, setStrategy] = useState('hybrid_rerank')
  const [topK, setTopK] = useState(5)
  const [hits, setHits] = useState<KbHit[] | null>(null)

  async function reload() {
    const data = await api<KbOverview>('/api/kb/overview')
    setOverview(data)
    if (!ctype || !data.content_types.some((item) => item.key === ctype))
      setCtype(data.content_types[0]?.key || 'faq')
  }

  async function loadStaging() {
    setStaging(await api<KbStaging>('/api/kb/staging'))
  }

  useEffect(() => {
    reload().catch((e) => setError(errorText(e)))
  }, [])

  useEffect(() => {
    if (tab === 'staging') loadStaging().catch((e) => setError(errorText(e)))
  }, [tab])

  function clear() {
    setError('')
    setNotice('')
  }

  async function run(task: () => Promise<string>) {
    if (busy) return
    setBusy(true)
    clear()
    try {
      setNotice(await task())
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const vectorize = () =>
    run(async () => {
      const result = await post<{ vectorized: number; chunk_stats: KbStats }>(
        '/api/kb/vectorize',
        {},
      )
      await reload()
      return `已补齐 ${result.vectorized} 个待向量块，知识库共 ${result.chunk_stats?.total ?? 0} 块。`
    })

  const doPreview = () =>
    run(async () => {
      const body = source ? { file: source } : { text, content_type: ctype }
      const result = await post<KbPreview>('/api/kb/preview', body)
      setPreview(result)
      setPreviewFromFile(Boolean(source))
      return `切出 ${result.total} 块，其中重复 ${result.duplicates} 块，关键条款 ${result.key_clause} 块。`
    })

  const doIngest = () =>
    run(async () => {
      const result = await post<KbIngest>('/api/kb/ingest', {
        text,
        content_type: ctype,
        vectorize: true,
      })
      await reload()
      setPreview(null)
      setText('')
      return `入库 ${result.inserted} 块，跳过重复 ${result.skipped} 块，向量化 ${
        result.vectorized ?? '未执行'
      } 块。`
    })

  const doSearch = () =>
    run(async () => {
      const result = await post<{ hits: KbHit[] }>('/api/kb/search', {
        q: query,
        strategy,
        top_k: topK,
      })
      setHits(result.hits)
      return `「${query}」按${STRATEGIES.find((s) => s.value === strategy)?.label}返回 ${
        result.hits.length
      } 条证据。`
    })

  const decide = (ids: number[], approve: boolean) =>
    run(async () => {
      const url = approve ? '/api/kb/staging/approve' : '/api/kb/staging/reject'
      await post(url, { ids })
      await Promise.all([loadStaging(), reload()])
      return approve ? `已采纳 ${ids.length} 条并写入知识库。` : `已弃用 ${ids.length} 条。`
    })

  const milvus = overview?.milvus
  const stats = overview?.chunks
  const pending = stats?.pending ?? 0

  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <h1>知识从哪里来，又怎么被检索到。</h1>
          <p>材料切块 → 入库与向量化 → 检索自测，每一步都按真实计数核对。</p>
        </div>
        <div className="button-group">
          <button
            className="icon-button"
            aria-label="刷新知识库状态"
            onClick={() => {
              clear()
              void reload().catch((e) => setError(errorText(e)))
            }}
          >
            <RefreshCw size={17} />
          </button>
          <button className="button secondary" disabled={busy || !pending} onClick={vectorize}>
            <Database size={16} />
            补齐向量
          </button>
        </div>
      </div>
      <div className="workspace-tabs">
        {(
          [
            ['overview', '概览', stats?.total ?? 0],
            ['ingest', '录入与预览', overview?.sources.length ?? 0],
            ['search', '检索自测', null],
            ['staging', '对话挖知识', overview?.staging?.total ?? 0],
          ] as [Tab, string, number | null][]
        ).map(([key, label, count]) => (
          <button
            className={tab === key ? 'selected' : ''}
            key={key}
            onClick={() => {
              clear()
              setTab(key)
            }}
          >
            {label}
            {count !== null && <span>{count}</span>}
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

      {tab === 'overview' && (
        <>
          <div className="kb-stats">
            <div className="kb-stat">
              <span>知识块</span>
              <strong>{stats?.total ?? '—'}</strong>
              <small>关键条款 {stats?.key_clause ?? 0} 块</small>
            </div>
            <div className="kb-stat">
              <span>待向量化</span>
              <strong>{stats?.pending ?? '—'}</strong>
              <small>{pending ? '点右上角「补齐向量」' : '数据库与向量库同步'}</small>
            </div>
            <div className="kb-stat">
              <span>Milvus</span>
              <strong>{milvus?.online ? milvus.count : '离线'}</strong>
              <small>{milvus?.online ? milvus.collection : milvus?.detail || '未连接'}</small>
            </div>
            <div className="kb-stat">
              <span>双写一致性</span>
              <strong>
                {overview?.consistent === null ? '—' : overview?.consistent ? '一致' : '不一致'}
              </strong>
              <small>
                {overview?.db_error ? `数据库：${overview.db_error}` : '按待处理数与向量数比对'}
              </small>
            </div>
          </div>
          <div className="kb-split">
            <section className="kb-panel">
              <h3>建库材料</h3>
              {overview?.sources.length ? (
                <div className="kb-list">
                  {overview.sources.map((item) => (
                    <div className="kb-row" key={item.file}>
                      <header>
                        <h4>
                          <FileText size={14} /> {item.file}
                        </h4>
                        <div className="kb-badges">
                          {item.present ? (
                            <Badge tone="ok">{item.content_type}</Badge>
                          ) : (
                            <Badge tone="warn">缺失</Badge>
                          )}
                          {item.features?.table_split && <Badge>表格切分</Badge>}
                          {item.features?.overlap && <Badge>重叠切分</Badge>}
                        </div>
                      </header>
                      <footer>
                        <span>{item.chars ?? 0} 字</span>
                        <span>{item.lines ?? 0} 行</span>
                        <span>{item.chunks ?? 0} 块</span>
                        <span>关键条款 {item.key_clause ?? 0}</span>
                        <span>{time(item.mtime)}</span>
                      </footer>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty
                  title="没有扫描到材料"
                  description="确认 data/kb 下有 Markdown 材料后再刷新。"
                />
              )}
            </section>
            <section className="kb-panel">
              <h3>最近入库</h3>
              {overview?.recent.length ? (
                <div className="kb-list">
                  {overview.recent.map((chunk) => (
                    <ChunkRow chunk={chunk} key={chunk.id} />
                  ))}
                </div>
              ) : (
                <Empty
                  title="知识库还是空的"
                  description="在「录入与预览」里粘一段正文或选择材料文件，预览后入库。"
                />
              )}
            </section>
          </div>
        </>
      )}

      {tab === 'ingest' && (
        <div className="kb-split">
          <section className="kb-panel">
            <h3>录入</h3>
            <div className="kb-form">
              <label>
                材料文件（预览用，不会写入）
                <select value={source} onChange={(e) => setSource(e.target.value)}>
                  <option value="">不选，直接贴正文</option>
                  {overview?.sources
                    .filter((item) => item.present)
                    .map((item) => (
                      <option key={item.file} value={item.file}>
                        {item.file}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                正文
                <textarea
                  value={text}
                  disabled={Boolean(source)}
                  maxLength={40000}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={
                    source
                      ? '已选择材料文件，下面按文件内容预览。'
                      : '贴一段 Markdown，二级标题会切成小节。'
                  }
                />
              </label>
              <label>
                内容类型
                <select
                  value={ctype}
                  disabled={Boolean(source)}
                  onChange={(e) => setCtype(e.target.value)}
                >
                  {overview?.content_types.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.key} · {item.desc}
                    </option>
                  ))}
                </select>
              </label>
              <div className="kb-actions">
                <button
                  className="button secondary"
                  disabled={busy || (!source && !text.trim())}
                  onClick={doPreview}
                >
                  <Layers size={16} />
                  预览切块
                </button>
                <button
                  className="button"
                  disabled={busy || Boolean(source) || !preview || previewFromFile || !text.trim()}
                  onClick={doIngest}
                >
                  <Check size={16} />
                  {busy ? '处理中…' : '入库并向量化'}
                </button>
              </div>
              <p className="kb-empty-hint">
                选择材料文件只能预览；要入库请直接贴正文，避免把整份材料重复写进知识库。
              </p>
            </div>
          </section>
          <section className="kb-panel">
            <h3>切块结果 {preview ? `· ${preview.total} 块` : ''}</h3>
            {preview ? (
              <>
                <div className="kb-badges" style={{ marginBottom: 12 }}>
                  <Badge>{preview.content_type}</Badge>
                  <Badge>{preview.chars} 字</Badge>
                  <Badge tone={preview.duplicates ? 'warn' : undefined}>
                    重复 {preview.duplicates}
                  </Badge>
                  <Badge>关键条款 {preview.key_clause}</Badge>
                  <Badge>{preview.features.sections} 个小节</Badge>
                  {!preview.dedup_known && <Badge tone="warn">查重不可用</Badge>}
                </div>
                <div className="kb-list">
                  {preview.chunks.map((chunk) => (
                    <ChunkRow chunk={chunk} key={chunk.seq} />
                  ))}
                </div>
              </>
            ) : (
              <Empty
                title="还没有预览"
                description="左侧贴正文或选材料文件，点「预览切块」看怎么切。"
              />
            )}
          </section>
        </div>
      )}

      {tab === 'search' && (
        <div className="kb-split">
          <section className="kb-panel">
            <h3>检索自测</h3>
            <div className="kb-form">
              <label>
                问一句
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="例如：退货运费谁出"
                />
              </label>
              <label>
                策略
                <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                  {STRATEGIES.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                取前几条
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value) || 5)}
                />
              </label>
              <div className="kb-actions">
                <button className="button" disabled={busy || !query.trim()} onClick={doSearch}>
                  <Search size={16} />
                  {busy ? '检索中…' : '检索'}
                </button>
              </div>
              <p className="kb-empty-hint">
                四种策略走的是同一份知识库：向量看语义，BM25
                看字面，混合取并集，重排按证据强弱排序。
              </p>
            </div>
          </section>
          <section className="kb-panel">
            <h3>命中证据 {hits ? `· ${hits.length} 条` : ''}</h3>
            {hits ? (
              hits.length ? (
                <div className="kb-list">
                  {hits.map((hit, index) => (
                    <div className="kb-row" key={`${hit.id ?? index}`}>
                      <header>
                        <h4>
                          [{index + 1}] {hit.question}
                        </h4>
                        <div className="kb-badges">
                          {hit.rerank_score !== null && (
                            <Badge>重排 {hit.rerank_score.toFixed(3)}</Badge>
                          )}
                          {hit.score !== null && <Badge>召回 {hit.score.toFixed(3)}</Badge>}
                        </div>
                      </header>
                      <p>{hit.answer}</p>
                      <footer>
                        <span>{hit.section_path || '(无标题层级)'}</span>
                        <span>{hit.content_type || '未标注'}</span>
                        <span>{hit.category}</span>
                      </footer>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty title="没有命中" description="换一种说法，或先确认知识库已完成向量化。" />
              )
            ) : (
              <Empty
                title="还没有检索"
                description="左侧输入一句用户会问的话，看证据排得对不对。"
              />
            )}
          </section>
        </div>
      )}

      {tab === 'staging' && (
        <section className="kb-panel">
          <h3>
            <Boxes size={14} /> 对话挖掘暂存
          </h3>
          {staging ? (
            <>
              <div className="kb-badges" style={{ marginBottom: 14 }}>
                <Badge>共 {staging.stats.total} 条</Badge>
                <Badge>{staging.stats.batches} 批</Badge>
                {staging.stats.latest_batch && <Badge>最近 {staging.stats.latest_batch}</Badge>}
                {Object.entries(staging.stats.counts).map(([status, count]) => (
                  <Badge key={status}>
                    {STAGING_STATUS[status] || status} {count}
                  </Badge>
                ))}
              </div>
              {(['kept', 'extracted', 'discarded'] as string[]).map((status) => {
                const rows = staging.rows[status] || []
                if (!rows.length) return null
                return (
                  <div className="detail-section" key={status}>
                    <h3>{STAGING_STATUS[status] || status}</h3>
                    <div className="kb-list">
                      {rows.map((row) => (
                        <div className="kb-row" key={row.id}>
                          <header>
                            <h4>{row.question}</h4>
                            {status === 'kept' && (
                              <div className="kb-actions">
                                <button
                                  className="button small"
                                  disabled={busy}
                                  onClick={() => decide([row.id], true)}
                                >
                                  <Check size={14} />
                                  采纳
                                </button>
                                <button
                                  className="button small secondary"
                                  disabled={busy}
                                  onClick={() => decide([row.id], false)}
                                >
                                  <X size={14} />
                                  弃用
                                </button>
                              </div>
                            )}
                          </header>
                          <p>{row.answer}</p>
                          <footer>
                            <span>{row.batch_no}</span>
                            <span>{row.source_ref}</span>
                          </footer>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })}
              {staging.stats.total === 0 && (
                <Empty
                  title="暂存区是空的"
                  description="运行 scripts.mine_knowledge 从已完成会话里挖问答，结果会先落到这里等人工采纳。"
                />
              )}
            </>
          ) : (
            <p className="loading">正在读取暂存区…</p>
          )}
        </section>
      )}
    </div>
  )
}
