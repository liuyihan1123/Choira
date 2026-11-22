import { useCallback, useEffect, useRef, useState } from 'react'
import { api, formatTime } from '../api'
import type { AuditEntry, RoleMeta, ScoreSummary, VersionDetail } from '../types'
import VersionEditor from './VersionEditor'

interface Props {
  roles: RoleMeta[]
  onPublished: () => void
}

const STATUS_TEXT: Record<string, string> = {
  draft: '待发布',
  published: '已发布',
  pending_omr: 'PDF 待识别',
}

const AUDIT_TEXT: Record<string, string> = {
  upload: '上传总谱',
  'api-upload': '上传总谱',
  'new-version': '新建版本',
  'mapping-save': '保存映射',
  publish: '发布分谱',
  'omr-attach': '回填 MusicXML',
  view: '团员查看',
  sign: '签发下载链接',
  download: '下载分谱',
}

export default function AdminView({ roles, onPublished }: Props) {
  const [scores, setScores] = useState<ScoreSummary[]>([])
  const [detail, setDetail] = useState<VersionDetail | null>(null)
  const [audits, setAudits] = useState<AuditEntry[]>([])
  const [view, setView] = useState<'pipeline' | 'audit'>('pipeline')
  const [error, setError] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [composer, setComposer] = useState('')
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)

  const loadScores = useCallback(async () => {
    const res = await api.scores()
    setScores(res.items)
  }, [])

  const loadAudit = useCallback(async () => {
    const res = await api.audit()
    setAudits(res.items)
  }, [])

  useEffect(() => {
    loadScores().catch((err: unknown) => setError(err instanceof Error ? err.message : '加载失败'))
    loadAudit().catch(() => undefined)
  }, [loadScores, loadAudit])

  const openScore = async (score: ScoreSummary) => {
    setError('')
    if (!score.latest_version) return
    try {
      setDetail(await api.version(score.latest_version.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载版本失败')
    }
  }

  const submitUpload = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!file) {
      setError('请选择一个 .musicxml / .mxl / .pdf 文件')
      return
    }
    setUploading(true)
    setError('')
    try {
      const created = await api.upload(file, title, composer)
      setDetail(created)
      setFile(null)
      setTitle('')
      setComposer('')
      if (fileRef.current) fileRef.current.value = ''
      await loadScores()
      await loadAudit()
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const refreshDetail = async () => {
    if (!detail) return
    const fresh = await api.version(detail.version_id)
    setDetail(fresh)
    await loadScores()
    await loadAudit()
  }

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setDragging(false)
    const dropped = event.dataTransfer.files?.[0]
    if (dropped) setFile(dropped)
  }

  return (
    <div className="admin">
      <div className="admin-top">
        <div className="admin-intro">
          <span className="eyebrow">PIPELINE</span>
          <h1>总谱入库 → 声部映射 → 发布分谱</h1>
          <p>
            MusicXML 里的每个 <code>&lt;part&gt;</code> 就是一份天然分谱。系统按 XML 级裁剪保留原谱排版，
            再把分谱按角色签发；PDF 则需要先转成 MusicXML 再进入同一条流水线。
          </p>
        </div>
        <div className="segmented">
          <button type="button" className={view === 'pipeline' ? 'active' : ''} onClick={() => setView('pipeline')}>
            流水线
          </button>
          <button type="button" className={view === 'audit' ? 'active' : ''} onClick={() => setView('audit')}>
            审计日志
          </button>
        </div>
      </div>

      {error && <div className="notice notice-error">{error}</div>}

      {view === 'audit' ? (
        <section className="card">
          <div className="card-head">
            <h2>最近的访问与操作</h2>
            <span className="muted">每一次取谱、签发、下载都会留痕</span>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>时间</th>
                <th>动作</th>
                <th>角色</th>
                <th>版本</th>
                <th>声部</th>
                <th>详情</th>
              </tr>
            </thead>
            <tbody>
              {audits.map((entry) => (
                <tr key={entry.id}>
                  <td className="mono">{formatTime(entry.ts)}</td>
                  <td>{AUDIT_TEXT[entry.action] ?? entry.action}</td>
                  <td>{roles.find((r) => r.code === entry.role)?.name ?? '—'}</td>
                  <td className="mono">{entry.version_id || '—'}</td>
                  <td className="mono">{entry.part_id || '—'}</td>
                  <td className="muted">{entry.detail || '—'}</td>
                </tr>
              ))}
              {audits.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    还没有记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      ) : (
        <>
          <section className="admin-grid">
            <form
              className={`upload-card card${dragging ? ' dragging' : ''}`}
              onSubmit={submitUpload}
              onDragOver={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <div className="card-head">
                <h2>① 上传总谱</h2>
                <span className="muted">.mxl / .musicxml / .xml / .pdf · 30MB 以内</span>
              </div>

              <label className="dropzone">
                <input
                  ref={fileRef}
                  type="file"
                  accept=".mxl,.musicxml,.xml,.pdf,application/pdf,application/vnd.recordare.musicxml+xml"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
                <strong>{file ? file.name : '把总谱拖到这里，或点击选择文件'}</strong>
                <span>
                  {file
                    ? `${Math.max(1, Math.round(file.size / 1024))} KB · 已就绪`
                    : 'MusicXML 会立即解析出声部；PDF 会先进入“待识别”队列'}
                </span>
              </label>

              <div className="field-row">
                <label className="field">
                  <span>曲名（可选，默认取文件内标题）</span>
                  <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Ubi caritas" />
                </label>
                <label className="field">
                  <span>作曲（可选）</span>
                  <input value={composer} onChange={(event) => setComposer(event.target.value)} placeholder="Maurice Duruflé" />
                </label>
              </div>

              <button type="submit" className="btn primary wide" disabled={uploading || !file}>
                {uploading ? '解析中…' : '入库并解析声部'}
              </button>
            </form>

            <div className="card score-table-card">
              <div className="card-head">
                <h2>② 曲目库</h2>
                <span className="muted">{scores.length} 首</span>
              </div>
              <table className="table">
                <thead>
                  <tr>
                    <th>曲目</th>
                    <th>版本</th>
                    <th>状态</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {scores.map((score) => (
                    <tr key={score.score_id} className={detail?.score_id === score.score_id ? 'selected' : ''}>
                      <td>
                        <strong>{score.title}</strong>
                        <div className="muted small-text">{score.composer || '佚名'}</div>
                      </td>
                      <td className="mono">
                        v{score.latest_version?.version_no ?? 1}
                        <div className="muted small-text">{score.version_count} 个版本</div>
                      </td>
                      <td>
                        <span className={`status-chip ${score.latest_version?.status ?? 'draft'}`}>
                          {STATUS_TEXT[score.latest_version?.status ?? 'draft']}
                        </span>
                      </td>
                      <td className="right">
                        <button type="button" className="btn ghost small" onClick={() => openScore(score)}>
                          管理
                        </button>
                      </td>
                    </tr>
                  ))}
                  {scores.length === 0 && (
                    <tr>
                      <td colSpan={4} className="muted">
                        还没有曲目，先上传一份总谱
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {detail ? (
            <VersionEditor
              detail={detail}
              roles={roles}
              onChanged={refreshDetail}
              onPublished={onPublished}
            />
          ) : (
            <div className="panel-empty small">
              <strong>选一首曲目开始配置声部映射</strong>
              <p>左侧曲目点“管理”，右侧会出现声部列表、角色映射矩阵与发布按钮。</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
