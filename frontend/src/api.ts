const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init)
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) {
        message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
      }
    } catch {
      /* 非 JSON 错误体，保留状态码 */
    }
    throw new ApiError(message)
  }
  const text = await res.text()
  return (text ? JSON.parse(text) : null) as T
}

export const api = {
  meta: () => request<import('./types').Meta>('/api/meta'),

  scores: () => request<{ items: import('./types').ScoreSummary[] }>('/api/scores'),

  version: (id: string) => request<import('./types').VersionDetail>(`/api/versions/${id}`),

  library: (role: string) =>
    request<{ role: string; role_name: string; items: import('./types').LibraryItem[] }>(
      `/api/library/${role}`,
    ),

  assetXml: async (assetId: number, role: string): Promise<string> => {
    const res = await fetch(`${BASE}/api/assets/${assetId}?role=${role}`)
    if (!res.ok) throw new ApiError('取谱失败，可能该分谱已被撤销')
    return res.text()
  },

  saveMapping: (versionId: string, mapping: Record<string, string[]>) =>
    request<import('./types').VersionDetail>(`/api/versions/${versionId}/assignments`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapping }),
    }),

  publish: (versionId: string, force = false) =>
    request<import('./types').VersionDetail>(`/api/versions/${versionId}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    }),

  sign: (assetId: number, role: string) =>
    request<{ url: string; expires_at: string }>(`/api/assets/${assetId}/sign?role=${role}`, {
      method: 'POST',
    }),

  upload: (file: File, title = '', composer = '') => {
    const form = new FormData()
    form.append('file', file)
    form.append('title', title)
    form.append('composer', composer)
    return request<import('./types').VersionDetail>('/api/scores', { method: 'POST', body: form })
  },

  newVersion: (scoreId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<import('./types').VersionDetail>(`/api/scores/${scoreId}/versions`, {
      method: 'POST',
      body: form,
    })
  },

  attachMusicXml: (versionId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<import('./types').VersionDetail>(
      `/api/versions/${versionId}/attach-musicxml`,
      { method: 'POST', body: form },
    )
  },

  audit: (limit = 40) =>
    request<{ items: import('./types').AuditEntry[] }>(`/api/audit?limit=${limit}`),

  /** 排练播放器：这个版本里全部声部的音轨 */
  play: (versionId: string) =>
    request<import('./types').Playlist>(`/api/play/${versionId}`),
}

/** 把接口返回的相对地址补成可直接 fetch 的绝对地址（开发态走 vite 代理） */
export function absoluteUrl(path: string): string {
  return path.startsWith('http') ? path : BASE + path
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatBytes(size: number): string {
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size > 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size} B`
}
