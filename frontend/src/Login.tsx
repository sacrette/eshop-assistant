import { ArrowRight, Headset, ShieldCheck, Workflow } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { api, post, setCsrf } from './api'
import type { User } from './types'
import { errorText } from './ui'

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [demo, setDemo] = useState<Pick<User, 'email' | 'name' | 'role'>[]>([])
  const [demoPassword, setDemoPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api<{ items: Pick<User, 'email' | 'name' | 'role'>[]; password?: string }>(
      '/api/auth/demo-accounts',
    )
      .then((r) => {
        setDemo(r.items)
        setDemoPassword(r.password || '')
      })
      .catch(() => undefined)
  }, [])
  function pick(account: Pick<User, 'email' | 'name' | 'role'>) {
    setEmail(account.email)
    if (demoPassword) setPassword(demoPassword)
    setError('')
  }
  async function login(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await post<{ user: User; csrf_token: string }>('/api/auth/login', {
        email,
        password,
      })
      setCsrf(result.csrf_token)
      onLogin(result.user)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <main className="login-layout">
      <section className="login-story">
        <a className="brand" href="/">
          <span className="brand-icon">
            <Headset size={24} />
          </span>
          <span>
            Eshop<span className="brand-sub">Assistant</span>
          </span>
        </a>
        <div className="login-copy">
          <span className="quiet-label">让每一次咨询都有下文</span>
          <h1>
            从一个问题，
            <br />
            到一次妥善处理。
          </h1>
          <p>把商品知识、订单信息与售后处理放在一起，让咨询有依据，让处理有进度。</p>
          <div className="story-flow">
            <div>
              <span>
                <Headset size={21} />
              </span>
              <b>理解诉求</b>
              <small>连接当前订单与对话</small>
            </div>
            <i />
            <div>
              <span>
                <ShieldCheck size={21} />
              </span>
              <b>确认依据</b>
              <small>核对政策与业务条件</small>
            </div>
            <i />
            <div>
              <span>
                <Workflow size={21} />
              </span>
              <b>跟进处理</b>
              <small>保留确认与处理记录</small>
            </div>
          </div>
        </div>
        <span className="login-footer">Eshop Assistant · 电商客服与售后工作台</span>
      </section>
      <section className="login-form-section">
        <form className="login-form" onSubmit={login}>
          <span className="login-symbol">
            <Headset size={28} />
          </span>
          <h2>欢迎回来</h2>
          <p>登录后，继续你的咨询或处理待办。</p>
          <label>
            邮箱
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="输入账号邮箱"
            />
          </label>
          <label>
            密码
            <input
              type="password"
              autoComplete="current-password"
              required
              maxLength={200}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="输入密码"
            />
          </label>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <button className="button login-submit" disabled={busy}>
            {busy ? '登录中…' : '登录工作台'}
            <ArrowRight size={18} />
          </button>
          {demo.length > 0 && (
            <div className="demo-accounts">
              <span>
                {demoPassword ? '选择演示身份，自动填入邮箱与密码' : '选择演示身份，再输入演示密码'}
              </span>
              <div>
                {demo.map((account) => (
                  <button
                    type="button"
                    key={account.email}
                    className={email === account.email ? 'selected' : ''}
                    onClick={() => pick(account)}
                  >
                    {account.name}
                    <small>{account.role === 'agent' ? '客服' : '用户'}</small>
                  </button>
                ))}
              </div>
            </div>
          )}
        </form>
      </section>
    </main>
  )
}
