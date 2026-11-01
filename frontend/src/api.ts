import type { StreamEvent } from './types'

let csrf = sessionStorage.getItem('eshop-csrf') || ''

export function setCsrf(value: string) {
  csrf = value
  if (value) sessionStorage.setItem('eshop-csrf', value)
  else sessionStorage.removeItem('eshop-csrf')
}

function headers(options: RequestInit): Headers {
  const h = new Headers(options.headers)
  if (options.body) h.set('Content-Type', 'application/json')
  if (options.method && !['GET', 'HEAD'].includes(options.method)) h.set('X-CSRF-Token', csrf)
  return h
}

async function check(response: Response): Promise<Response> {
  if (response.ok) return response
  if (response.status === 401 && !response.url.endsWith('/api/auth/login')) {
    window.dispatchEvent(new Event('eshop:unauthorized'))
  }
  const body = await response.json().catch(() => ({}))
  const detail = typeof body.detail === 'string' ? body.detail : '请求失败，请检查填写内容后重试'
  throw new Error(detail)
}

export async function api<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await check(
    await fetch(url, { ...options, credentials: 'same-origin', headers: headers(options) }),
  )
  return response.json() as Promise<T>
}

export function post<T>(url: string, body: unknown): Promise<T> {
  return api<T>(url, { method: 'POST', body: JSON.stringify(body) })
}

export async function stream(
  url: string,
  body: unknown,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
) {
  const options = { method: 'POST', body: JSON.stringify(body) }
  const response = await check(
    await fetch(url, { ...options, signal, credentials: 'same-origin', headers: headers(options) }),
  )
  const reader = response.body?.getReader()
  if (!reader) throw new Error('浏览器无法接收流式响应')
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (data === '[DONE]') return
        if (data) {
          const event = JSON.parse(data) as StreamEvent
          if (frame.includes('event: error') || event.message)
            throw new Error(event.message || '服务暂时不可用')
          onEvent(event)
        }
      }
      if (done) break
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
