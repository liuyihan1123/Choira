import { useEffect, useState, type CSSProperties } from 'react'
import { api } from './api'
import type { Meta, RoleCode } from './types'
import MemberView from './components/MemberView'
import AdminView from './components/AdminView'

type Tab = 'member' | 'admin'

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [tab, setTab] = useState<Tab>('member')
  const [role, setRole] = useState<RoleCode>('S')
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    api.meta().then(setMeta).catch(() => undefined)
  }, [])

  const roles = meta?.roles ?? []

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <svg viewBox="0 0 40 40" className="brand-mark" role="presentation">
            <rect width="40" height="40" rx="9" fill="#221d18" />
            <path d="M9 14h22M9 19h22M9 24h22M9 29h22" stroke="#f5f0e6" strokeWidth="1.3" strokeLinecap="round" />
            <circle cx="18" cy="24" r="3" fill="#9c3d2e" />
          </svg>
          <div className="brand-text">
            <strong>ChoirParts</strong>
            <span>合唱团分谱分发</span>
          </div>
        </div>

        <nav className="tabs" aria-label="视图切换">
          <button type="button" className={tab === 'member' ? 'active' : ''} onClick={() => setTab('member')}>
            团员端
          </button>
          <button type="button" className={tab === 'admin' ? 'active' : ''} onClick={() => setTab('admin')}>
            管理台
          </button>
        </nav>

        {tab === 'member' ? (
          <div className="role-switch">
            <span className="role-switch-label">当前身份</span>
            {roles.map((item) => (
              <button
                key={item.code}
                type="button"
                className={`role-pill${role === item.code ? ' active' : ''}`}
                style={{ '--role': item.color } as CSSProperties}
                onClick={() => setRole(item.code)}
                title={`${item.name} / ${item.en}`}
              >
                <i />
                {item.name}
              </button>
            ))}
          </div>
        ) : (
          <div className="header-stats">
            {meta && (
              <>
                <span>{meta.stats.scores} 首曲目</span>
                <span>{meta.stats.assets} 份分谱</span>
                <span>{meta.stats.audit} 条审计</span>
              </>
            )}
          </div>
        )}
      </header>

      <main className="app-main">
        {tab === 'member' ? (
          <MemberView key={nonce} roles={roles} role={role} />
        ) : (
          <AdminView roles={roles} onPublished={() => setNonce((n) => n + 1)} />
        )}
      </main>

      <footer className="app-footer">
        <span>内部格式 MusicXML · 拆分方式 XML 级裁剪（保留歌词与排版）· 前端渲染 OSMD</span>
        <span className="mono">demo build · 无登录鉴权，勿直接上线</span>
      </footer>
    </div>
  )
}
