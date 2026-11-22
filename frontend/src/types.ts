export type RoleCode = 'S' | 'A' | 'T' | 'B' | 'ACCOMP' | 'CONDUCTOR'

export interface RoleMeta {
  code: RoleCode
  name: string
  en: string
  short: string
  color: string
}

export interface Part {
  part_id: string
  index: number
  name: string
  abbreviation: string
  staves: number
  voices: string[]
  note_count: number
  multi_voice: boolean
  extractable: boolean
  suggested_role: RoleCode | null
  confidence: number
  warnings: string[]
  roles: string[]
}

export type VersionStatus = 'draft' | 'published' | 'pending_omr'

export interface VersionDetail {
  version_id: string
  score_id: string
  version_no: number
  status: VersionStatus
  source_kind: string
  source_name: string
  has_musicxml: boolean
  has_pdf: boolean
  title: string
  composer: string
  notes: string
  created_at: string
  published_at: string | null
  parts: Part[]
  mapping: Record<string, string[]>
  unsplittable_parts: string[]
  asset_count: number
  assets: { id: number; role: string; part_id: string; sha256: string; size: number }[]
}

export interface ScoreSummary {
  score_id: string
  title: string
  composer: string
  created_at: string
  latest_version: { id: string; version_no: number; status: VersionStatus; source_kind: string } | null
  published_version: { id: string; version_no: number; status: VersionStatus } | null
  version_count: number
}

export interface LibraryAsset {
  id: number
  part_id: string
  part_name: string
  abbreviation: string
  sha256: string
}

export interface LibraryItem {
  version_id: string
  score_id: string
  title: string
  composer: string
  version_no: number
  published_at: string | null
  assets: LibraryAsset[]
}

/** 排练播放器：一个版本里的全部声部音轨（不分角色，所有人看到的都一样） */
export interface PlaylistPart {
  part_id: string
  name: string
  abbreviation: string
  roles: string[]
  suggested_role: RoleCode | null
  staves: number
  note_count: number
  extractable: boolean
  available: boolean
  duration: number
  size: number
  audio_url: string | null
}

export interface Playlist {
  version_id: string
  version_no: number
  status: VersionStatus
  title: string
  composer: string
  duration: number
  parts: PlaylistPart[]
}

export interface AuditEntry {
  id: number
  ts: string
  action: string
  role: string
  version_id: string
  part_id: string
  ip: string
  detail: string
}

export interface Meta {
  roles: RoleMeta[]
  stats: { scores: number; versions: number; parts: number; assets: number; audit: number }
  limits: { upload_mb: number }
}
