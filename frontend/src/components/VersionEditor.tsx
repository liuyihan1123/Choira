import { useEffect, useState } from 'react'
import { api, formatBytes, formatTime } from '../api'
import type { RoleMeta, VersionDetail } from '../types'

interface Props {
  detail: VersionDetail
  roles: RoleMeta[]
  onChanged: () => Promise<void>
  onPublished: () => void
}

const STATUS_TEXT: Record<string, string> = {
  draft: '待发布',
  published: '已发布',
  pending_omr: 'PDF 待识别',
}

const SOURCE_TEXT: Record<string, string> = {
  musicxml: 'MusicXML',
  mxl: 'MXL 压缩包',
  pdf: 'PDF 扫描件',
  'pdf+musicxml': 'PDF + 回填 MusicXML',
}

export default function VersionEditor({ detail, roles, onChanged, onPublished }: Props) {
  const [mapping, setMapping] = useState<Record<string, string[]>>(detail.mapping ?? {})
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [force, setForce] = useState(false)
  const [attaching, setAttaching] = useState(false)

  useEffect(() => {
    setMapping(detail.mapping ?? {})
    setError('')
    setNotice('')
  }, [detail])

  const locked = detail.status === 'published'
  const mappedCount = Object.values(mapping).reduce((sum, list) => sum + list.length, 0)

  const toggle = (role: string, partId: string) => {
    if (locked) return
    setMapping((prev) => {
      const list = new Set(prev[role] ?? [])
      if (list.has(partId)) list.delete(partId)
      else list.add(partId)
      return { ...prev, [role]: [...list] }
    })
  }

  const applySuggestions = () => {
    const next: Record<string, string[]> = {}
    for (const part of detail.parts) {
      if (!part.suggested_role || part.confidence < 0.6 || !part.extractable) continue
      next[part.suggested_role] = [...(next[part.suggested_role] ?? []), part.part_id]
    }
    setMapping(next)
    setNotice('已按名称识别结果填充，请核对后保存。')
  }

  const cleanMapping = () =>
    Object.fromEntries(
      Object.entries(mapping)
        .map(([role, parts]) => [role, parts.filter(Boolean)] as const)
        .filter(([, parts]) => parts.length > 0),
    )

  const save = async () => {
    setSaving(true)
    setError('')
    setNotice('')
    try {
      await api.saveMapping(detail.version_id, cleanMapping())
      await onChanged()
      setNotice('映射已保存，可以发布。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const publish = async () => {
    setPublishing(true)
    setError('')
    setNotice('')
    try {
      const saved = await api.saveMapping(detail.version_id, cleanMapping())
      void saved
      await api.publish(detail.version_id, force)
      await onChanged()
      onPublished()
      setNotice('已发布：每个角色都拿到独立分谱文件。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '发布失败')
    } finally {
      setPublishing(false)
    }
  }

  const attach = async (file: File | undefined) => {
    if (!file) return
    setAttaching(true)
    setError('')
    try {
      await api.attachMusicXml(detail.version_id, file)
      await onChanged()
      setNotice('已回填 MusicXML，可以继续做声部映射。')
    } catch (err) {
      setError(err instanceof Error ? err.message : '回填失败')
    } finally {
      setAttaching(false)
    }
  }

  const titleFor = (role: string) => roles.find((r) => r.code === role)?.name ?? role

  return (
    <section className="card version-card">
      <div className="card-head version-head">
        <div>
          <span className="eyebrow">③ 映射与发布</span>
          <h2>
            {detail.title} <span className="version-inline">v{detail.version_no}</span>
          </h2>
          <p className="muted">
            {detail.composer || '佚名'} · {SOURCE_TEXT[detail.source_kind] ?? detail.source_kind} ·
            {detail.published_at ? ` 发布于 ${formatTime(detail.published_at)}` : ` 创建于 ${formatTime(detail.created_at)}`}
          </p>
        </div>
        <div className="version-actions">
          <span className={`status-chip ${detail.status}`}>{STATUS_TEXT[detail.status] ?? detail.status}</span>
          <button type="button" className="btn ghost small" onClick={applySuggestions} disabled={locked}>
            按建议填充
          </button>
          <button type="button" className="btn ghost small" onClick={save} disabled={locked || saving}>
            {saving ? '保存中…' : '保存映射'}
          </button>
          <button
            type="button"
            className="btn primary small"
            onClick={publish}
            disabled={locked || publishing || mappedCount === 0}
          >
            {publishing ? '生成分谱…' : locked ? '已发布' : '发布分谱'}
          </button>
        </div>
      </div>

      {error && <div className="notice notice-error">{error}</div>}
      {notice && <div className="notice notice-ok">{notice}</div>}

      {detail.notes && <div className="notice notice-info">{detail.notes}</div>}

      {detail.unsplittable_parts.length > 0 && (
        <div className="notice notice-warn">
          <strong>无法按 part 拆分：</strong>
          {detail.unsplittable_parts.join('、')} —— 这些声部在总谱里合写在一个 part 内（常见于 SATB 叠在钢琴双谱表上），
          XML 级裁剪切不开。请先在 MuseScore 里拆成独立 part 后重新上传，或勾选下方“强制发布”整段保留。
          <label className="force-check">
            <input type="checkbox" checked={force} onChange={(event) => setForce(event.target.checked)} />
            允许强制发布（把整个 part 原样发给该角色）
          </label>
        </div>
      )}

      {detail.has_pdf && !detail.has_musicxml && (
        <div className="pdf-block">
          <div className="pdf-preview">
            <iframe src={`/api/versions/${detail.version_id}/pdf`} title="PDF 总谱预览" />
          </div>
          <div className="pdf-drop">
            <h3>PDF 还不能直接拆分</h3>
            <p>
              PDF 里没有声部语义。请用 Audiveris / MuseScore 把这份总谱转成 MusicXML（人工校对一遍），
              再把转换结果传回来——声部列表会自动出现。
            </p>
            <label className="btn ghost file-btn">
              {attaching ? '回填中…' : '上传转好的 MusicXML'}
              <input
                type="file"
                accept=".musicxml,.xml,.mxl"
                onChange={(event) => attach(event.target.files?.[0])}
              />
            </label>
          </div>
        </div>
      )}

      {detail.parts.length > 0 ? (
        <table className="matrix">
          <thead>
            <tr>
              <th className="matrix-part">总谱中的声部（part）</th>
              <th className="matrix-meta">谱表 / 声部 / 音符</th>
              {roles.map((role) => (
                <th key={role.code} style={{ color: role.color }}>
                  {role.short}
                  <span>{role.name}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {detail.parts.map((part) => (
              <tr key={part.part_id} className={part.extractable ? '' : 'row-warn'}>
                <td className="matrix-part">
                  <strong>{part.name}</strong>
                  <div className="muted small-text">
                    <span className="mono">{part.part_id}</span>
                    {part.suggested_role && (
                      <span className="suggest-tag">
                        建议 {titleFor(part.suggested_role)} · {Math.round(part.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  {part.warnings.map((warning) => (
                    <div key={warning} className="warn-text">
                      {warning}
                    </div>
                  ))}
                </td>
                <td className="matrix-meta mono">
                  {part.staves} 谱表 /{' '}
                {part.voices.length ? `${part.voices.length} 声部` : '未标声部'} / {part.note_count} 音符
                </td>
                {roles.map((role) => {
                  const checked = (mapping[role.code] ?? []).includes(part.part_id)
                  return (
                    <td key={role.code} className="matrix-cell">
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={locked || !part.extractable}
                          onChange={() => toggle(role.code, part.part_id)}
                        />
                        <span style={{ background: role.color, opacity: checked ? 1 : 0.12 }} />
                      </label>
                    </td>
                  )
                })}
              </tr>
            ))}
            {detail.parts.length === 0 && (
              <tr>
                <td colSpan={roles.length + 2} className="muted">
                  还没有解析到声部
                </td>
              </tr>
            )}
          </tbody>
        </table>
      ) : (
        <div className="notice notice-info">
          还没有解析到声部。PDF 版本需要先回填 MusicXML，之后才会出现 part 列表和角色映射矩阵。
        </div>
      )}

      {detail.assets.length > 0 && (
        <div className="assets">
          <h3>已生成的分谱文件</h3>
          <ul>
            {detail.assets.map((asset) => {
              const part = detail.parts.find((p) => p.part_id === asset.part_id)
              return (
                <li key={asset.id}>
                  <span className="role-dot" style={{ background: roles.find((r) => r.code === asset.role)?.color }} />
                  <strong>{titleFor(asset.role)}</strong>
                  <span className="muted">{part?.name ?? asset.part_id}</span>
                  <span className="mono muted">{formatBytes(asset.size)}</span>
                  <span className="mono muted">sha256 {asset.sha256.slice(0, 10)}…</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}
