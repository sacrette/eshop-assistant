import {
  ArrowRight,
  CheckCheck,
  ClipboardList,
  MessageSquareText,
  Package,
  RefreshCw,
  Search,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, post } from './api'
import type { Case, User } from './types'
import { Empty, errorText, money, Status, statusName, time } from './ui'

interface Ticket {
  id: string
  description: string
  type: string
  status: string
  resolution: string | null
  created_at: string
}

export default function Cases({ user }: { user: User }) {
  const [items, setItems] = useState<Case[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [tab, setTab] = useState('cases')
  const [selected, setSelected] = useState<Case | null>(null)
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [history, setHistory] = useState<{ role: string; content: string }[]>([])
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const staff = user.role === 'agent'

  async function refresh() {
    const [cases, queue] = await Promise.all([
      api<{ items: Case[] }>('/api/commerce/cases'),
      api<{ items: Ticket[] }>('/api/commerce/tickets'),
    ])
    setItems(cases.items)
    setTickets(queue.items)
    if (selected) setSelected(await api<Case>(`/api/commerce/cases/${selected.id}`))
    if (ticket) setTicket(queue.items.find((item) => item.id === ticket.id) || null)
  }
  useEffect(() => {
    refresh()
      .catch((e) => setError(errorText(e)))
      .finally(() => setLoading(false))
  }, [])
  async function select(item: Case) {
    setError('')
    setNote('')
    setSelected(null)
    try {
      setSelected(await api<Case>(`/api/commerce/cases/${item.id}`))
    } catch (e) {
      setError(errorText(e))
    }
  }
  async function selectTicket(item: Ticket) {
    setTicket(item)
    setNote('')
    setError('')
    setHistory([])
    if (staff) {
      try {
        const result = await api<{ items: typeof history }>(
          `/api/commerce/tickets/${item.id}/messages`,
        )
        setHistory(result.items)
      } catch (e) {
        setError(errorText(e))
      }
    }
  }
  async function change(status: string) {
    if (!selected || busy || !note.trim()) return
    setBusy(true)
    setError('')
    try {
      const item = await post<Case>(`/api/commerce/cases/${selected.id}/transition`, {
        status,
        version: selected.version,
        note: note.trim(),
      })
      setSelected(item)
      setNote('')
      await refresh()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  async function resolve() {
    if (!ticket || busy || !note.trim()) return
    setBusy(true)
    setError('')
    try {
      await post(`/api/commerce/tickets/${ticket.id}/resolve`, { note: note.trim() })
      setTicket({ ...ticket, status: '已处理', resolution: note.trim() })
      setNote('')
      await refresh()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const visible = items.filter(
    (c) =>
      (filter === 'all' || c.status === filter) &&
      `${c.id}${c.order_id}${c.reason}`.toLowerCase().includes(search.toLowerCase()),
  )
  return (
    <div className="workspace-page">
      <div className="page-intro">
        <div>
          <h1>{staff ? '每一笔售后，都有清楚的进度。' : '你的售后，我们持续跟进。'}</h1>
          <p>
            {staff
              ? '核对订单与申请信息，留下处理依据，再推进下一步。'
              : '查看申请状态和客服处理记录。'}
          </p>
        </div>
        <button
          className="button secondary"
          onClick={() => refresh().catch((e) => setError(errorText(e)))}
        >
          <RefreshCw size={16} />
          刷新
        </button>
      </div>
      <div className="workspace-tabs">
        <button
          className={tab === 'cases' ? 'selected' : ''}
          onClick={() => {
            setTab('cases')
            setError('')
          }}
        >
          <ClipboardList size={17} />
          售后申请<span>{items.filter((c) => c.status === 'pending').length}</span>
        </button>
        <button
          className={tab === 'tickets' ? 'selected' : ''}
          onClick={() => {
            setTab('tickets')
            setError('')
          }}
        >
          <MessageSquareText size={17} />
          人工待办<span>{tickets.filter((t) => t.status === '待处理').length}</span>
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="case-layout">
        <section className="queue-panel">
          <div className="queue-controls">
            <div className="search-input">
              <Search size={16} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索单号或申请原因"
                aria-label="搜索申请"
              />
            </div>
            {tab === 'cases' && (
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                aria-label="筛选状态"
              >
                <option value="all">全部状态</option>
                {['pending', 'approved', 'rejected', 'completed'].map((s) => (
                  <option value={s} key={s}>
                    {statusName[s]}
                  </option>
                ))}
              </select>
            )}
          </div>
          {loading ? (
            <p className="loading">正在读取待办…</p>
          ) : tab === 'cases' ? (
            <>
              {visible.length === 0 && (
                <Empty title="没有匹配的申请" description="提交的售后申请会出现在这里。" />
              )}
              {visible.map((item) => (
                <button
                  key={item.id}
                  className={`queue-item ${selected?.id === item.id ? 'active' : ''}`}
                  onClick={() => void select(item)}
                  disabled={busy}
                >
                  <div>
                    <span className="case-number">{item.id}</span>
                    <Status value={item.status} />
                  </div>
                  <h3>{item.reason}</h3>
                  <p>订单 {item.order_id}</p>
                  <footer>
                    <span>{time(item.created_at)}</span>
                    <ArrowRight size={16} />
                  </footer>
                </button>
              ))}
            </>
          ) : (
            <>
              {tickets.length === 0 && (
                <Empty title="暂无人工待办" description="对话中确认转人工后，待办会显示在这里。" />
              )}
              {tickets
                .filter((t) => `${t.id}${t.description}`.includes(search))
                .map((item) => (
                  <button
                    key={item.id}
                    className={`queue-item ${ticket?.id === item.id ? 'active' : ''}`}
                    onClick={() => void selectTicket(item)}
                  >
                    <div>
                      <span className="case-number">{item.id}</span>
                      <Status value={item.status} />
                    </div>
                    <h3>{item.type}工单</h3>
                    <p>{item.description}</p>
                    <footer>
                      {time(item.created_at)}
                      <ArrowRight size={16} />
                    </footer>
                  </button>
                ))}
            </>
          )}
        </section>
        <section className="case-detail">
          {tab === 'cases' ? (
            selected ? (
              <>
                <div className="detail-header">
                  <span className="quiet-label">售后申请详情</span>
                  <div>
                    <h2>{selected.reason}</h2>
                    <Status value={selected.status} />
                  </div>
                  <p>{selected.id}</p>
                </div>
                {selected.order && (
                  <div className="detail-order">
                    <span className="product-icon">
                      <Package size={28} strokeWidth={1.4} />
                    </span>
                    <div>
                      <strong>{selected.order.product}</strong>
                      <small>{selected.order.order_id}</small>
                      <span>{selected.order.status}</span>
                    </div>
                    <b>{money(selected.order.amount)}</b>
                  </div>
                )}
                <div className="detail-section">
                  <h3>申请说明</h3>
                  <p>{selected.description || '用户未填写补充说明。'}</p>
                </div>
                <div className="detail-section">
                  <h3>处理记录</h3>
                  <ol className="timeline">
                    {selected.events?.map((event) => (
                      <li key={event.id}>
                        <span className="timeline-dot" />
                        <div>
                          <strong>{statusName[event.action] || event.action}</strong>
                          <time>{time(event.created_at)}</time>
                          <p>{event.note}</p>
                          <small>操作账号：{event.actor_id}</small>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
                {staff && ['pending', 'approved'].includes(selected.status) && (
                  <div className="case-decision">
                    <label>
                      {selected.status === 'pending' ? '审核意见' : '处理结果'}
                      <textarea
                        value={note}
                        maxLength={2000}
                        onChange={(e) => setNote(e.target.value)}
                        rows={3}
                        placeholder="填写核实情况、处理依据和后续安排"
                      />
                    </label>
                    <div>
                      {selected.status === 'pending' ? (
                        <>
                          <button
                            className="button secondary"
                            disabled={busy || !note.trim()}
                            onClick={() => void change('rejected')}
                          >
                            驳回申请
                          </button>
                          <button
                            className="button"
                            disabled={busy || !note.trim()}
                            onClick={() => void change('approved')}
                          >
                            <CheckCheck size={17} />
                            批准申请
                          </button>
                        </>
                      ) : (
                        <button
                          className="button"
                          disabled={busy || !note.trim()}
                          onClick={() => void change('completed')}
                        >
                          记录处理完成
                        </button>
                      )}
                    </div>
                    <small>完成表示本地售后处理结束，实际退款到账需支付渠道确认。</small>
                  </div>
                )}
              </>
            ) : (
              <Empty title="选择一笔售后申请" description="在左侧查看申请，核对订单与处理记录。" />
            )
          ) : ticket ? (
            <>
              <div className="detail-header">
                <span className="quiet-label">人工处理待办</span>
                <div>
                  <h2>{ticket.type}工单</h2>
                  <Status value={ticket.status} />
                </div>
                <p>{ticket.id}</p>
              </div>
              <div className="detail-section">
                <h3>用户诉求</h3>
                <p>{ticket.description}</p>
              </div>
              {ticket.resolution && (
                <div className="detail-section">
                  <h3>处理结果</h3>
                  <p>{ticket.resolution}</p>
                </div>
              )}
              {history.length > 0 && (
                <div className="detail-section">
                  <h3>相关对话</h3>
                  <div className="transcript">
                    {history.map((m, i) => (
                      <p key={i}>
                        <b>{m.role === 'user' ? '用户' : '助手'}</b>
                        {m.content}
                      </p>
                    ))}
                  </div>
                </div>
              )}
              {staff && ticket.status === '待处理' && (
                <div className="case-decision">
                  <label>
                    处理记录
                    <textarea
                      rows={4}
                      maxLength={2000}
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="记录已经核实和完成的事项"
                    />
                  </label>
                  <button
                    className="button"
                    disabled={busy || !note.trim()}
                    onClick={() => void resolve()}
                  >
                    记录处理完成
                  </button>
                </div>
              )}
            </>
          ) : (
            <Empty
              title="选择一条人工待办"
              description="查看用户诉求与相关会话，再记录处理结果。"
            />
          )}
        </section>
      </div>
    </div>
  )
}
