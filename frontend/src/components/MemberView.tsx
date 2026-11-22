import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { api, formatTime } from '../api'
import type { LibraryAsset, LibraryItem, RoleCode, RoleMeta } from '../types'
import ScoreViewer from './ScoreViewer'
import PartMixer from './PartMixer'

interface Props {
  roles: RoleMeta[]
  role: RoleCode
}

const WATERMARK_COUNT = 9

export default function MemberView({ roles, role }: Props) {
  const [items, setItems] = useState<LibraryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selection, setSelection] = useState<{ item: LibraryItem; asset: LibraryAsset } | null>(null)
  const [xml, setXml] = useState('')
  const [fetching, setFetching] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [busy, setBusy] = useState(false)

  const roleMeta = useMemo(() => roles.find((r) => r.code === role), [roles, role])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    setItems([])
    setSelection(null)
    setXml('')
    api
      .library(role)
      .then((res) => {
        if (!alive) return
        setItems(res.items)
        const first = res.items[0]
        if (first && first.assets[0]) setSelection({ item: first, asset: first.assets[0] })
      })
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [role])

  const assetId = selection?.asset.id

  useEffect(() => {
    if (!selection) {
      setXml('')
      return
    }
    let alive = true
    setFetching(true)
    api
      .assetXml(selection.asset.id, role)
      .then((text) => alive && setXml(text))
      .catch((err: unknown) => alive && setError(err instanceof Error ? err.message : '取谱失败'))
      .finally(() => alive && setFetching(false))
    return () => {
      alive = false
    }
  }, [assetId, role, selection])

  const download = async () => {
    if (!selection) return
    setBusy(true)
    try {
      const { url } = await api.sign(selection.asset.id, role)
      window.location.href = url
    } catch (err) {
      setError(err instanceof Error ? err.message : '下载失败')
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <div className="panel-empty">正在加载 {roleMeta?.name ?? ''} 的分谱…</div>
  }

  return (
    <div className="member-layout">
      <aside className="member-list">
        <div className="list-head">
          <div>
            <span className="eyebrow">MY PARTS</span>
            <h2>我的分谱</h2>
          </div>
          <span className="counter">{items.length}</span>
        </div>

        {error && <div className="notice notice-error">{error}</div>}

        {items.length === 0 && !error && (
          <div className="panel-empty small">
            <strong>还没有发布给「{roleMeta?.name}」的分谱</strong>
            <p>管理员在管理台完成声部映射并发布后，这里会自动出现对应分谱。</p>
          </div>
        )}

        <ul className="score-cards">
          {items.map((item) => {
            const active = selection?.item.version_id === item.version_id
            return (
              <li key={item.version_id}>
                <button
                  type="button"
                  className={`score-card${active ? ' active' : ''}`}
                  onClick={() => item.assets[0] && setSelection({ item, asset: item.assets[0] })}
                >
                  <div className="score-card-top">
                    <h3>{item.title}</h3>
                    <span className="version-tag">v{item.version_no}</span>
                  </div>
                  <p className="score-card-composer">{item.composer || '佚名'}</p>
                  <div className="part-chips">
                    {item.assets.map((asset) => (
                      <span
                        key={asset.id}
                        className={`part-chip${selection?.asset.id === asset.id ? ' current' : ''}`}
                        onClick={(event) => {
                          event.stopPropagation()
                          setSelection({ item, asset })
                        }}
                      >
                        {asset.part_name}
                      </span>
                    ))}
                  </div>
                  <span className="score-card-time">发布于 {formatTime(item.published_at)}</span>
                </button>
              </li>
            )
          })}
        </ul>

        <p className="list-footnote">
          你只会看到「{roleMeta?.name}」的分谱。其他声部的文件不会出现在这里，也无法通过链接访问。
        </p>
      </aside>

      <section className="viewer">
        {selection ? (
          <>
            <header className="viewer-head">
              <div>
                <h2>{selection.item.title}</h2>
                <p>
                  {selection.item.composer || '佚名'} · {selection.item.assets.length > 1 ? '多声部' : '单声部'}分谱 ·
                  <span className="version-inline"> v{selection.item.version_no}</span>
                </p>
              </div>
              <div className="viewer-head-right">
                <span className="role-badge" style={{ '--role': roleMeta?.color } as CSSProperties}>
                  {roleMeta?.name}
                </span>
                <span className={`status-chip ${selection.item.published_at ? 'published' : 'draft'}`}>
                  已发布
                </span>
              </div>
            </header>

            <div className="viewer-toolbar">
              <div className="part-tabs">
                {selection.item.assets.map((asset) => (
                  <button
                    key={asset.id}
                    type="button"
                    className={selection.asset.id === asset.id ? 'active' : ''}
                    onClick={() => setSelection({ item: selection.item, asset })}
                  >
                    {asset.part_name}
                    <em>{asset.abbreviation}</em>
                  </button>
                ))}
              </div>

              <div className="toolbar-actions">
                <div className="zoom">
                  <button type="button" onClick={() => setZoom((z) => Math.max(0.6, +(z - 0.1).toFixed(2)))}>
                    −
                  </button>
                  <span>{Math.round(zoom * 100)}%</span>
                  <button type="button" onClick={() => setZoom((z) => Math.min(2, +(z + 0.1).toFixed(2)))}>
                    +
                  </button>
                </div>
                <button type="button" className="btn ghost" onClick={() => window.print()}>
                  打印
                </button>
                <button type="button" className="btn primary" onClick={download} disabled={busy}>
                  {busy ? '签发中…' : '下载分谱'}
                </button>
              </div>
            </div>

            <div className="score-paper">
              {fetching ? <div className="paper-status">正在取谱…</div> : <ScoreViewer xml={xml} zoom={zoom} />}
              <div className="watermark" aria-hidden="true">
                {Array.from({ length: WATERMARK_COUNT }).map((_, index) => (
                  <span key={index}>
                    {roleMeta?.name} · {selection.item.title} · v{selection.item.version_no} · 仅限本人排练使用
                  </span>
                ))}
              </div>

              {/* 排练播放器叠在谱面上：所有声部都能听，谱面仍只显示本人分谱 */}
              <PartMixer
                key={selection.item.version_id}
                versionId={selection.item.version_id}
                role={role}
                roles={roles}
              />
            </div>
          </>
        ) : (
          <div className="panel-empty">
            <StaffGlyph />
            <strong>选择左侧的一份分谱开始看谱</strong>
            <p>分谱由管理员从总谱中裁出，保留歌词与力度记号，并按你的角色单独签发。</p>
          </div>
        )}
      </section>
    </div>
  )
}

export function StaffGlyph() {
  return (
    <svg viewBox="0 0 240 90" className="staff-glyph" role="presentation">
      {[18, 30, 42, 54, 66].map((y) => (
        <line key={y} x1="8" y1={y} x2="232" y2={y} stroke="currentColor" strokeWidth="1" opacity="0.45" />
      ))}
      <ellipse cx="78" cy="54" rx="7" ry="5" fill="currentColor" transform="rotate(-18 78 54)" />
      <line x1="84" y1="54" x2="84" y2="20" stroke="currentColor" strokeWidth="1.6" />
      <ellipse cx="132" cy="42" rx="7" ry="5" fill="currentColor" transform="rotate(-18 132 42)" />
      <line x1="138" y1="42" x2="138" y2="16" stroke="currentColor" strokeWidth="1.6" />
      <ellipse cx="186" cy="46" rx="7" ry="5" fill="currentColor" transform="rotate(-18 186 46)" />
      <line x1="192" y1="46" x2="192" y2="18" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  )
}
