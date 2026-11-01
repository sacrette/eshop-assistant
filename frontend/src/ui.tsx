import { Package, X } from 'lucide-react'
import * as Dialog from '@radix-ui/react-dialog'
import { useRef, useState } from 'react'
import { post } from './api'
import type { Case, Order } from './types'

export const money = (amount: number) =>
  new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(amount)
export const time = (value?: string | null) =>
  value
    ? new Date(value.endsWith('Z') ? value : value + 'Z').toLocaleString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    : '—'
export const statusName: Record<string, string> = {
  pending: '待审核',
  approved: '已批准',
  rejected: '已驳回',
  completed: '已处理',
  submitted: '提交申请',
}
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : '操作失败，请重试'

export function Status({ value }: { value: string }) {
  return <span className={`status status-${value}`}>{statusName[value] || value}</span>
}

export function Empty({ title, description }: { title: string; description: string }) {
  return (
    <div className="empty">
      <Package size={30} strokeWidth={1.3} />
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  )
}

export function RefundDialog({
  order,
  conversationId,
  close,
  onCreated,
}: {
  order: Order
  conversationId?: number | null
  close: () => void
  onCreated: (item: Case) => void
}) {
  const [reason, setReason] = useState('七天无理由')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const key = useRef(crypto.randomUUID())
  async function submit() {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const item = await post<Case>('/api/commerce/cases', {
        order_id: order.order_id,
        reason,
        description,
        idempotency_key: key.current,
        conversation_id: conversationId || null,
      })
      onCreated(item)
      close()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !busy) close()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title>确认售后申请</Dialog.Title>
          <Dialog.Description>
            申请提交后进入人工审核，你可以在「我的售后」查看进度。
          </Dialog.Description>
          <Dialog.Close className="icon-button dialog-close" aria-label="关闭" disabled={busy}>
            <X size={19} />
          </Dialog.Close>
          <div className="order-summary">
            <Package size={26} />
            <div>
              <strong>{order.product}</strong>
              <small>{order.order_id}</small>
            </div>
            <b>{money(order.amount)}</b>
          </div>
          <label>
            申请原因
            <select
              value={reason}
              disabled={busy}
              onChange={(e) => {
                setReason(e.target.value)
                key.current = crypto.randomUUID()
              }}
            >
              {['七天无理由', '质量问题', '发错货', '不想要了', '其他'].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            补充说明
            <textarea
              value={description}
              disabled={busy}
              maxLength={2000}
              rows={4}
              onChange={(e) => {
                setDescription(e.target.value)
                key.current = crypto.randomUUID()
              }}
              placeholder="描述商品情况，帮助客服更快了解问题"
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <button className="button secondary" disabled={busy} onClick={close}>
              暂不申请
            </button>
            <button className="button" disabled={busy} onClick={submit}>
              {busy ? '正在提交…' : '确认提交申请'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function TicketDialog({
  conversationId,
  initial,
  ticketType,
  close,
  onCreated,
}: {
  conversationId: number
  initial: string
  ticketType: string
  close: () => void
  onCreated: (id: string) => void
}) {
  const [description, setDescription] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const key = useRef(crypto.randomUUID())
  async function submit() {
    setBusy(true)
    setError('')
    try {
      const result = await post<{ ticket_no: string }>('/api/actions/create-ticket', {
        conversation_id: conversationId,
        description,
        ticket_type: ticketType,
        idempotency_key: key.current,
      })
      onCreated(result.ticket_no)
      close()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !busy) close()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title>确认人工协助请求</Dialog.Title>
          <Dialog.Description>
            确认后创建客服待办，客服将结合本次对话处理你的问题。
          </Dialog.Description>
          <Dialog.Close className="icon-button dialog-close" aria-label="关闭" disabled={busy}>
            <X size={19} />
          </Dialog.Close>
          <label>
            需要协助的事项
            <textarea
              value={description}
              disabled={busy}
              maxLength={2000}
              rows={5}
              onChange={(e) => {
                setDescription(e.target.value)
                key.current = crypto.randomUUID()
              }}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <button className="button secondary" disabled={busy} onClick={close}>
              取消
            </button>
            <button
              className="button"
              disabled={busy || !description.trim()}
              onClick={() => void submit()}
            >
              {busy ? '正在提交…' : '确认创建待办'}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
