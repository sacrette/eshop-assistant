import {
  BookOpen,
  ClipboardList,
  Headset,
  Library,
  LogOut,
  MessageSquareText,
  PanelLeftClose,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, post, setCsrf } from './api'
import Cases from './Cases'
import Chat from './Chat'
import Knowledge from './Knowledge'
import KnowledgeBase from './KnowledgeBase'
import Login from './Login'
import type { SystemStatus, User } from './types'
import { errorText } from './ui'

type Page = 'chat' | 'cases' | 'knowledge' | 'kb'

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const [page, setPage] = useState<Page>('chat')
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [error, setError] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  function loggedIn(account: User) {
    setUser(account)
    const requested = window.location.pathname.split('/')[1]
    const target: Page =
      requested === 'cases'
        ? 'cases'
        : requested === 'kb' && account.role === 'agent'
          ? 'kb'
          : requested === 'knowledge' && account.role === 'agent'
            ? 'knowledge'
            : account.role === 'agent'
              ? 'cases'
              : 'chat'
    setPage(target)
    setError('')
  }
  useEffect(() => {
    api<User>('/api/auth/me')
      .then(async (account) => {
        const result = await api<{ csrf_token: string }>('/api/auth/csrf')
        setCsrf(result.csrf_token)
        loggedIn(account)
      })
      .catch(() => setUser(null))
      .finally(() => setReady(true))
  }, [])
  useEffect(() => {
    if (user)
      api<SystemStatus>('/api/system/status')
        .then(setStatus)
        .catch((e) => setError(errorText(e)))
    else setStatus(null)
  }, [user])
  useEffect(() => {
    function pop() {
      if (user) loggedIn(user)
    }
    window.addEventListener('popstate', pop)
    return () => window.removeEventListener('popstate', pop)
  }, [user])
  useEffect(() => {
    function expired() {
      setUser(null)
      setCsrf('')
    }
    window.addEventListener('eshop:unauthorized', expired)
    return () => window.removeEventListener('eshop:unauthorized', expired)
  }, [])
  function navigate(next: Page) {
    setPage(next)
    history.pushState({}, '', next === 'chat' ? '/' : `/${next}`)
  }
  async function logout() {
    try {
      await post('/api/auth/logout', {})
      setUser(null)
      setCsrf('')
      history.replaceState({}, '', '/')
    } catch (e) {
      setError(errorText(e))
    }
  }
  if (!ready)
    return (
      <div className="boot-screen">
        <Headset size={32} />
        <p>正在打开工作台…</p>
      </div>
    )
  if (!user) return <Login onLogin={loggedIn} />
  const titles = {
    chat: ['智能客服', '咨询、订单与售后协助'],
    cases: [user.role === 'agent' ? '售后工作台' : '我的售后', '申请进度与人工处理记录'],
    knowledge: ['知识运营', '从问题缺口到审核发布'],
    kb: ['知识库', '材料切块、入库与检索自测'],
  }
  return (
    <div className={`app-layout ${collapsed ? 'nav-collapsed' : ''}`}>
      <aside className="sidebar">
        <a
          className="brand"
          href="/"
          onClick={(e) => {
            e.preventDefault()
            navigate(user.role === 'agent' ? 'cases' : 'chat')
          }}
        >
          <span className="brand-icon">
            <Headset size={23} />
          </span>
          <span className="brand-name">
            Eshop<span className="brand-sub">Assistant</span>
          </span>
        </a>
        <div className="workspace-name">
          <span className="workspace-dot" />
          <span>电商服务工作台</span>
        </div>
        <nav aria-label="工作台导航">
          {user.role === 'customer' && (
            <button
              className={page === 'chat' ? 'active' : ''}
              onClick={() => navigate('chat')}
              title="智能客服"
            >
              <MessageSquareText size={19} />
              <span>智能客服</span>
            </button>
          )}
          <button
            className={page === 'cases' ? 'active' : ''}
            onClick={() => navigate('cases')}
            title="售后工作台"
          >
            <ClipboardList size={19} />
            <span>{user.role === 'agent' ? '售后工作台' : '我的售后'}</span>
          </button>
          {user.role === 'agent' && (
            <button
              className={page === 'knowledge' ? 'active' : ''}
              onClick={() => navigate('knowledge')}
              title="知识运营"
            >
              <BookOpen size={19} />
              <span>知识运营</span>
            </button>
          )}
          {user.role === 'agent' && (
            <button
              className={page === 'kb' ? 'active' : ''}
              onClick={() => navigate('kb')}
              title="知识库"
            >
              <Library size={19} />
              <span>知识库</span>
            </button>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <Headset size={18} />
            <p>
              有依据的回答，
              <br />
              有记录的处理。
            </p>
          </div>
          <button
            className="collapse-nav"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? '展开导航' : '收起导航'}
          >
            <PanelLeftClose size={18} />
            <span>收起导航</span>
          </button>
        </div>
      </aside>
      <div className="app-content">
        <header className="topbar">
          <div className="breadcrumb">
            <span>工作台</span>
            <i>/</i>
            <strong>{titles[page][0]}</strong>
          </div>
          <div className="topbar-right">
            {status && user.role === 'agent' && (
              <span className="system-status">
                <span className={status.observability.enabled ? 'dot on' : 'dot'} />
                LangSmith {status.observability.enabled ? '已启用' : '未启用'}
              </span>
            )}
            <span className="account-avatar">{user.name.slice(-1)}</span>
            <span className="account-name">
              {user.name}
              <small>{user.role === 'agent' ? '客服' : '用户'}</small>
            </span>
            <button
              className="icon-button"
              title="退出登录"
              aria-label="退出登录"
              onClick={() => void logout()}
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <div className="page-heading">
          <h2>{titles[page][0]}</h2>
          <span>{titles[page][1]}</span>
        </div>
        {error && (
          <div className="error app-error" role="alert">
            {error}
          </div>
        )}
        <main className="main-content">
          {page === 'chat' ? (
            <Chat key={user.id} user={user} status={status} />
          ) : page === 'cases' ? (
            <Cases key={user.id} user={user} />
          ) : page === 'kb' ? (
            <KnowledgeBase />
          ) : (
            <Knowledge />
          )}
        </main>
      </div>
    </div>
  )
}
