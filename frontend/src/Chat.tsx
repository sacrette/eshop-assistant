import {
  ArrowUp,
  PanelRightOpen,
  PanelRightClose,
  Check,
  Headset,
  MessageSquare,
  Package,
  Plus,
  RefreshCw,
  ThumbsDown,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, post, stream } from './api'
import CitedText from './CitedText'
import ProcessingReport, { type ProcessingInfo } from './ProcessingReport'
import type {
  Action,
  Citation,
  Conversation,
  Message,
  Order,
  Pending,
  StreamEvent,
  SystemStatus,
  User,
} from './types'
import { errorText, money, RefundDialog, TicketDialog } from './ui'

const nodeLabels: Record<string, string> = {
  resolve_reference: '理解上下文与补全问题',
  classify_intent: '识别咨询意图',
  retrieve_knowledge: '混合检索、重排与证据检查',
  confidence_check: '选择回答或兜底路径',
  fetch_order: '查询并校验订单',
  retrieve_policy: '检索相关业务政策',
  main_agent: '生成回复与选择工具',
  agent_tools: '执行受约束业务工具',
  fallback_reply: '拒答并收集知识缺口',
  script_reply: '生成场景回复',
  complaint_reply: '提供投诉处理入口',
  cancel_reply: '取消本次操作',
  log: '保存本轮消息',
}
const detailLabels: Record<string, string> = {
  intent: '意图',
  intent_confidence: '意图置信度',
  self_check: '证据自评说明',
  resolved_query: '标准问法',
  evidence_confidence: '证据置信度',
  fallback_source: '兜底来源',
}

export default function Chat({ user, status }: { user: User; status: SystemStatus | null }) {
  const [processOpen, setProcessOpen] = useState(false)
  const [steps, setSteps] = useState<{ name: string; detail?: Record<string, string | number> }[]>(
    [],
  )
  const [processing, setProcessing] = useState<ProcessingInfo>({})
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [cid, setCid] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [orders, setOrders] = useState<Order[]>([])
  const [pending, setPending] = useState<Pending | null>(null)
  const [actions, setActions] = useState<Action[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [activity, setActivity] = useState('')
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null)
  const [notice, setNotice] = useState('')
  const [ticketDraft, setTicketDraft] = useState<{ description: string; type: string } | null>(null)
  const [feedback, setFeedback] = useState<string[]>([])
  const bottom = useRef<HTMLDivElement>(null)
  const abort = useRef<AbortController | null>(null)
  const storageKey = `eshop-conversation:${user.id}`
  const loadEpoch = useRef(0)
  const tools: Record<string, string> = {
    query_order: '已查询订单',
    query_product: '已查询商品',
    query_faq: '已检索知识',
    query_logistics: '已查询物流',
    create_ticket: '已处理工单请求',
    query_warranty: '已查询保修',
    query_return_status: '已查询售后记录',
  }

  async function refresh() {
    const [cs, os] = await Promise.all([
      api<{ items: Conversation[] }>('/api/conversations'),
      api<{ items: Order[] }>('/api/commerce/orders'),
    ])
    setConversations(cs.items)
    setOrders(os.items)
  }
  async function load(id: number) {
    const epoch = ++loadEpoch.current
    setError('')
    setPending(null)
    setActions([])
    try {
      const [history, waiting] = await Promise.all([
        api<{ items: { role: Message['role']; content: string; citations?: Citation[] }[] }>(
          `/api/conversations/${id}/messages`,
        ),
        api<{ interrupt: Pending | null; actions: Action[]; processing?: typeof processing }>(
          `/api/conversations/${id}/pending`,
        ),
      ])
      if (epoch !== loadEpoch.current) return
      setCid(id)
      localStorage.setItem(storageKey, String(id))
      setMessages(history.items.map((m, i) => ({ ...m, id: `history-${id}-${i}` })))
      setSteps([])
      setProcessing(waiting.processing || {})
      setPending(waiting.interrupt)
      setActions(waiting.actions || [])
    } catch (e) {
      if (epoch === loadEpoch.current) setError(errorText(e))
    }
  }
  useEffect(() => {
    refresh().catch((e) => setError(errorText(e)))
    const saved = Number(localStorage.getItem(storageKey))
    if (saved) void load(saved)
    return () => {
      abort.current?.abort()
      loadEpoch.current++
    }
  }, [user.id])
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [messages, pending])

  async function run(resume?: Record<string, unknown>) {
    if (busy) return
    const text = draft.trim()
    if (!resume && !text) return
    setBusy(true)
    setError('')
    setActivity('正在理解问题…')
    setSteps([])
    setProcessing({})
    setActions([])
    const assistantId = crypto.randomUUID()
    if (!resume) {
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'user', content: text },
        { id: assistantId, role: 'assistant', content: '' },
      ])
      setDraft('')
    } else
      setMessages((current) => [...current, { id: assistantId, role: 'assistant', content: '' }])
    abort.current = new AbortController()
    let hadDelta = false
    let requestCid = cid
    try {
      const body = resume
        ? { conversation_id: cid, interrupt_id: pending?.interrupt_id, ...resume }
        : { message: text, conversation_id: cid }
      await stream(
        resume ? '/api/actions/resume' : '/api/chat',
        body,
        (event: StreamEvent) => {
          if (event.conversation_id) {
            requestCid = event.conversation_id
            setCid(event.conversation_id)
            localStorage.setItem(storageKey, String(event.conversation_id))
          }
          if (event.delta) {
            hadDelta = true
            setActivity('')
            setMessages((current) =>
              current.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + event.delta } : m,
              ),
            )
          }
          if (event.event === 'step') {
            setSteps((current) => [...current, { name: event.name || '', detail: event.detail }])
          }
          if (event.event === 'tool') {
            setActivity(tools[event.name || ''] || '已完成工具调用')
            setSteps((current) => [...current, { name: `tool:${event.name}` }])
          }
          if (event.event === 'citations')
            setMessages((current) =>
              current.map((m) =>
                m.id === assistantId ? { ...m, citations: event.items as Citation[] } : m,
              ),
            )
          if (event.event === 'interrupt')
            setPending({ ...event, type: event.kind, interrupt_id: event.interrupt_id! })
          if (event.event === 'actions') setActions(event.items as Action[])
        },
        abort.current.signal,
      )
      if (resume) {
        const waiting = await api<{ interrupt: Pending | null }>(
          `/api/conversations/${cid}/pending`,
        )
        setPending(waiting.interrupt)
      }
      if (requestCid) {
        const result = await api<{ processing: ProcessingInfo }>(
          `/api/conversations/${requestCid}/pending`,
        )
        setProcessing(result.processing || {})
      }
      await refresh()
    } catch (e) {
      if (!(e instanceof DOMException && e.name === 'AbortError')) setError(errorText(e))
    } finally {
      if (!hadDelta) setMessages((current) => current.filter((m) => m.id !== assistantId))
      setBusy(false)
      setActivity('')
    }
  }
  function newConversation() {
    loadEpoch.current++
    setCid(null)
    setMessages([])
    setSteps([])
    setProcessing({})
    setPending(null)
    setActions([])
    setError('')
    setNotice('')
    localStorage.removeItem(storageKey)
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    void run()
  }
  async function downvote(message: Message) {
    const index = messages.findIndex((m) => m.id === message.id)
    const question = messages
      .slice(0, index)
      .reverse()
      .find((m) => m.role === 'user')?.content
    if (!cid || !question) return
    try {
      await post('/api/feedback', { conversation_id: cid, question, rating: 'down' })
      setFeedback((items) => [...items, message.id])
      setNotice('已记录未解决的问题，后续将由运营审核。')
    } catch (e) {
      setError(errorText(e))
    }
  }
  return (
    <div className={`chat-layout process-layout ${processOpen ? 'process-expanded' : ''}`}>
      <aside className="conversation-column">
        <button className="button secondary new-chat" onClick={newConversation} disabled={busy}>
          <Plus size={17} />
          新建咨询
        </button>
        <div className="section-label">
          最近咨询<span>{conversations.length}</span>
        </div>
        <div className="conversation-items">
          {conversations.map((c) => (
            <button
              className={`conversation-item ${cid === c.id ? 'active' : ''}`}
              key={c.id}
              onClick={() => void load(c.id)}
              disabled={busy}
            >
              <MessageSquare size={17} />
              <span>
                <strong>{c.title || c.preview || `咨询 ${c.id}`}</strong>
                <small>{c.status}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="column-foot">
          <ShieldNote />
        </div>
      </aside>
      <section className="chat-main">
        <div className="panel-toolbar">
          <div className="toolbar-identity">
            <span className="assistant-avatar">
              <Headset size={20} />
            </span>
            <div>
              <strong>电商服务助手</strong>
              <small>咨询解答与售后协助</small>
            </div>
          </div>
          <button
            className="icon-button"
            title="刷新咨询列表"
            aria-label="刷新咨询列表"
            onClick={() => refresh().catch((e) => setError(errorText(e)))}
          >
            <RefreshCw size={17} />
          </button>
        </div>
        <div className="message-scroll" aria-live="polite">
          {messages.length === 0 && (
            <div className="chat-welcome">
              <span className="welcome-mark">
                <Headset size={34} strokeWidth={1.5} />
              </span>
              <h2>{user.name}，有什么可以帮你？</h2>
              <p>
                商品怎么选、订单到哪了，或是需要申请售后，
                <br />
                都可以从这里开始。
              </p>
              <div className="suggestions">
                {[
                  '查询我的订单物流',
                  '商品收到后如何申请退货？',
                  '智能猫砂盆 Pro 的保修政策是什么？',
                ].map((text) => (
                  <button key={text} onClick={() => setDraft(text)}>
                    <MessageSquare size={15} />
                    {text}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <div className={`message message-${m.role}`} key={m.id}>
              <span className="message-avatar">
                {m.role === 'user' ? user.name.slice(-1) : <Headset size={16} />}
              </span>
              <div className="message-content">
                <span className="message-author">{m.role === 'user' ? user.name : '服务助手'}</span>
                <div className="message-text">
                  {m.content ? (
                    <CitedText text={m.content} citations={m.citations} />
                  ) : (
                    <span className="muted">正在处理…</span>
                  )}
                </div>
                {m.role === 'assistant' && m.content && (
                  <button
                    className="text-button feedback-button"
                    disabled={busy || feedback.includes(m.id)}
                    onClick={() => void downvote(m)}
                  >
                    <ThumbsDown size={12} />
                    {feedback.includes(m.id) ? '已记录' : '未解决我的问题'}
                  </button>
                )}
              </div>
            </div>
          ))}
          {pending && (
            <div className="confirmation">
              <span className="quiet-label">需要你的确认</span>
              <h3>
                {(pending.type || pending.kind) === 'select_order'
                  ? '这次需要处理哪一笔订单？'
                  : '确认创建人工处理工单'}
              </h3>
              {(pending.type || pending.kind) === 'select_order' ? (
                <div className="selection-orders">
                  {pending.orders?.map((o) => (
                    <button
                      key={o.order_id}
                      disabled={busy}
                      onClick={() => void run({ order_id: o.order_id })}
                    >
                      <Package size={20} />
                      <span>
                        <strong>{o.product}</strong>
                        <small>{o.order_id}</small>
                      </span>
                      <b>{money(o.amount)}</b>
                    </button>
                  ))}
                </div>
              ) : (
                <>
                  <p>{pending.preview?.description}</p>
                  <button
                    className="button"
                    disabled={busy}
                    onClick={() => void run({ confirmed: true })}
                  >
                    <Check size={16} />
                    确认创建工单
                  </button>
                </>
              )}
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void run({ cancelled: true })}
              >
                <X size={14} />
                取消本次操作
              </button>
            </div>
          )}
          {actions
            .filter((a) => a.type === 'refund_form')
            .map((action, i) => (
              <div className="inline-action" key={i}>
                <Package size={19} />
                <div>
                  <strong>核对信息后提交售后申请</strong>
                  <small>订单 {action.draft?.order_id}</small>
                </div>
                <button
                  className="button small"
                  disabled={busy}
                  onClick={() => {
                    const order = orders.find((o) => o.order_id === action.draft?.order_id)
                    if (order) setSelectedOrder(order)
                    else setError('订单不在当前账号下，请刷新订单列表')
                  }}
                >
                  查看申请
                </button>
              </div>
            ))}
          {actions
            .filter((a) => a.type === 'select_order' && (a.orders?.length ?? 0) > 0)
            .map((action, i) => (
              <div className="confirmation" key={`orders-${i}`}>
                <span className="quiet-label">你的订单</span>
                <h3>要处理哪一笔订单？</h3>
                <div className="selection-orders">
                  {action.orders?.map((o) => (
                    <button
                      key={o.order_id}
                      disabled={busy}
                      onClick={() => void run({ order_id: o.order_id })}
                    >
                      <Package size={20} />
                      <span>
                        <strong>{o.product}</strong>
                        <small>{o.order_id}</small>
                      </span>
                      <b>{money(o.amount)}</b>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          {cid && actions.some((a) => ['transfer_human', 'create_ticket'].includes(a.type)) && (
            <div className="inline-action">
              <Headset size={19} />
              <div>
                <strong>需要客服进一步协助？</strong>
                <small>确认诉求后创建人工处理待办</small>
              </div>
              <button
                className="button small"
                disabled={busy}
                onClick={() => {
                  const draft = actions.find((a) => a.type === 'create_ticket')?.draft
                  setTicketDraft({
                    description:
                      draft?.description ||
                      [...messages].reverse().find((m) => m.role === 'user')?.content ||
                      '',
                    type: draft?.ticket_type || '咨询',
                  })
                }}
              >
                申请人工协助
              </button>
            </div>
          )}
          {notice && (
            <div className="notice" role="status">
              {notice}
            </div>
          )}
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <div ref={bottom} />
        </div>
        <div className="composer-wrap">
          {activity && (
            <div className="activity">
              <span className="pulse" />
              {activity}
            </div>
          )}
          {status && !status.model_configured && (
            <p className="configuration-note">
              聊天模型尚未配置。你仍可以在右侧查看订单和提交售后申请。
            </p>
          )}
          <form className="composer" onSubmit={submit}>
            <textarea
              value={draft}
              rows={2}
              maxLength={6000}
              disabled={busy || !!pending}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  void run()
                }
              }}
              placeholder={pending ? '请先确认或取消上方操作' : '描述你的问题，也可以附上订单号…'}
              aria-label="咨询内容"
            />
            <button
              className="send-button"
              type="submit"
              disabled={busy || !!pending || !draft.trim() || !status?.model_configured}
              aria-label="发送消息"
            >
              <ArrowUp size={21} />
            </button>
          </form>
          <small className="composer-hint">
            Enter 发送，Shift + Enter 换行 · 业务操作将在确认后提交
          </small>
        </div>
      </section>
      <aside className={`process-column ${processOpen ? 'open' : ''}`}>
        <button
          className="process-toggle"
          aria-expanded={processOpen}
          aria-controls="processing-panel"
          aria-label={processOpen ? '收起处理说明' : '展开处理说明'}
          onClick={() => setProcessOpen(!processOpen)}
        >
          {processOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
          <span>处理说明</span>
        </button>
        {processOpen && (
          <div id="processing-panel" className="process-content">
            <h3>{busy ? '正在处理本次咨询' : '本轮处理记录'}</h3>
            <p className="editor-hint">根据实际执行记录展示意图、检索证据、校验结果与工具返回。</p>
            {steps.length > 0 ? (
              <ol className="process-steps">
                {steps.map((step, index) => (
                  <li key={index}>
                    <strong>
                      {step.name.startsWith('tool:')
                        ? tools[step.name.slice(5)] || step.name.slice(5)
                        : nodeLabels[step.name] || step.name}
                    </strong>
                    {step.detail &&
                      Object.entries(step.detail).map(([key, value]) => (
                        <small key={key}>
                          {detailLabels[key] || key}：{String(value)}
                        </small>
                      ))}
                  </li>
                ))}
              </ol>
            ) : !processing.resolved_query ? (
              <p className="muted">发送咨询后显示处理记录。</p>
            ) : null}
            <ProcessingReport info={processing} />
            {busy && <p className="muted">{activity || '正在生成回答…'}</p>}
          </div>
        )}
      </aside>
      {selectedOrder && (
        <RefundDialog
          order={selectedOrder}
          conversationId={cid}
          close={() => setSelectedOrder(null)}
          onCreated={(item) => {
            setActions([])
            setNotice(`申请 ${item.id} 已提交，等待客服审核。`)
          }}
        />
      )}
      {ticketDraft && cid && (
        <TicketDialog
          conversationId={cid}
          initial={ticketDraft.description}
          ticketType={ticketDraft.type}
          close={() => setTicketDraft(null)}
          onCreated={(id) => {
            setActions([])
            setNotice(`人工处理待办 ${id} 已创建，可在「我的售后」查看。`)
          }}
        />
      )}
    </div>
  )
}

function ShieldNote() {
  return (
    <p>
      <Check size={14} />
      只展示当前账号的咨询与订单
    </p>
  )
}
