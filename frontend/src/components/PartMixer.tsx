import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { absoluteUrl, api } from '../api'
import type { Playlist, PlaylistPart, RoleCode, RoleMeta } from '../types'

interface Props {
  versionId: string
  role: RoleCode
  roles: RoleMeta[]
}

function formatClock(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

function audioContextCtor(): typeof AudioContext | null {
  const w = window as unknown as {
    AudioContext?: typeof AudioContext
    webkitAudioContext?: typeof AudioContext
  }
  return w.AudioContext ?? w.webkitAudioContext ?? null
}

/**
 * 声部排练播放器：把每个声部的 MP3 解码成 AudioBuffer，用 Web Audio 从同一时刻
 * 起播，因此天然采样级同步；静音/独奏只是各自 GainNode 的音量变化，播放中切换
 * 不会重新起播、不会影响其它声部。
 *
 * 不用 N 个 <audio> 标签，是因为多个媒体元素各有自己的时钟，几秒之后就会互相
 * 漂移，五六个声部叠在一起会听出"糊"。
 */
export default function PartMixer({ versionId, role, roles }: Props) {
  const [playlist, setPlaylist] = useState<Playlist | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [muted, setMuted] = useState<Record<string, boolean>>({})
  const [solo, setSolo] = useState<Record<string, boolean>>({})
  const [master, setMaster] = useState(0.85)

  const ctxRef = useRef<AudioContext | null>(null)
  const masterRef = useRef<GainNode | null>(null)
  const masterValueRef = useRef(0.85)
  const buffersRef = useRef<Map<string, AudioBuffer>>(new Map())
  const gainsRef = useRef<Map<string, GainNode>>(new Map())
  const sourcesRef = useRef<Map<string, AudioBufferSourceNode>>(new Map())
  const anchorRef = useRef(0) // ctx.currentTime - 已播放秒数
  const offsetRef = useRef(0)
  const barRef = useRef<HTMLDivElement | null>(null)

  const parts = useMemo<PlaylistPart[]>(() => playlist?.parts ?? [], [playlist])
  const duration = playlist?.duration ?? 0
  const playable = useMemo(() => parts.filter((part) => part.available), [parts])

  const roleColor = useCallback(
    (part: PlaylistPart) => {
      const code = part.roles[0] ?? part.suggested_role ?? ''
      return roles.find((item) => item.code === code)?.color ?? 'var(--ink-faint)'
    },
    [roles],
  )

  const isOwnPart = (part: PlaylistPart) => part.roles.includes(role)

  // 注意：这个回调必须是稳定的（依赖为空）。它被下面的载入 effect 依赖，
  // 一旦随总音量变化重建，拖一下音量条就会触发整段音频重新下载与解码。
  const ensureContext = useCallback((): AudioContext | null => {
    if (ctxRef.current) return ctxRef.current
    const Ctor = audioContextCtor()
    if (!Ctor) return null
    const ctx = new Ctor()
    const masterNode = ctx.createGain()
    masterNode.gain.value = masterValueRef.current
    masterNode.connect(ctx.destination)
    ctxRef.current = ctx
    masterRef.current = masterNode
    return ctx
  }, [])

  const stopSources = useCallback(() => {
    sourcesRef.current.forEach((source) => {
      try {
        source.stop()
      } catch {
        /* 已经结束的 source 不能再 stop */
      }
      try {
        source.disconnect()
      } catch {
        /* 忽略重复断开 */
      }
    })
    sourcesRef.current.clear()
  }, [])

  /** 某个声部此刻是否应该发声（独奏优先，静音其次） */
  const audible = useCallback(
    (partId: string) => {
      const anySolo = parts.some((part) => solo[part.part_id])
      return anySolo ? Boolean(solo[partId]) && !muted[partId] : !muted[partId]
    },
    [parts, solo, muted],
  )

  const startAt = useCallback(
    (offset: number) => {
      const ctx = ctxRef.current
      const masterNode = masterRef.current
      if (!ctx || !masterNode) return
      stopSources()
      const when = ctx.currentTime + 0.06
      let started = 0
      parts
        .filter((part) => part.available)
        .forEach((part) => {
          const buffer = buffersRef.current.get(part.part_id)
          if (!buffer) return
          const source = ctx.createBufferSource()
          source.buffer = buffer
          let gain = gainsRef.current.get(part.part_id)
          if (!gain) {
            gain = ctx.createGain()
            gainsRef.current.set(part.part_id, gain)
            gain.connect(masterNode)
          }
          gain.gain.value = audible(part.part_id) ? 1 : 0
          source.connect(gain)
          source.start(when, Math.min(offset, Math.max(buffer.duration - 0.02, 0)))
          sourcesRef.current.set(part.part_id, source)
          started += 1
        })
      if (!started) return
      anchorRef.current = when - offset
      setElapsed(offset)
      setPlaying(true)
    },
    [parts, audible, stopSources],
  )

  // 载入播放列表 + 解码全部音轨
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    setReady(false)
    setPlaying(false)
    setElapsed(0)
    offsetRef.current = 0
    buffersRef.current.clear()
    stopSources()

    api
      .play(versionId)
      .then(async (data) => {
        if (cancelled) return
        setPlaylist(data)
        const ctx = ensureContext()
        const available = data.parts.filter((part) => part.available && part.audio_url)
        if (!ctx || available.length === 0) {
          if (!cancelled) setReady(available.length > 0)
          return
        }
        await Promise.all(
          available.map(async (part) => {
            const response = await fetch(absoluteUrl(part.audio_url as string))
            if (!response.ok) throw new Error(`「${part.name}」音频加载失败`)
            const buffer = await ctx.decodeAudioData(await response.arrayBuffer())
            if (!cancelled) buffersRef.current.set(part.part_id, buffer)
          }),
        )
        if (!cancelled) setReady(true)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '音频加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [versionId, ensureContext, stopSources])

  // 播放进度
  useEffect(() => {
    if (!playing) return
    let frame = 0
    const loop = () => {
      const ctx = ctxRef.current
      if (!ctx) return
      const position = ctx.currentTime - anchorRef.current
      if (duration > 0 && position >= duration) {
        offsetRef.current = 0
        stopSources()
        setPlaying(false)
        setElapsed(0)
        return
      }
      setElapsed(position)
      frame = requestAnimationFrame(loop)
    }
    frame = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(frame)
  }, [playing, duration, stopSources])

  // 静音 / 独奏 / 总音量：只改增益，不打断播放
  useEffect(() => {
    masterValueRef.current = master
    const ctx = ctxRef.current
    if (!ctx) return
    const anySolo = parts.some((part) => solo[part.part_id])
    parts.forEach((part) => {
      const gain = gainsRef.current.get(part.part_id)
      if (!gain) return
      const on = anySolo ? Boolean(solo[part.part_id]) && !muted[part.part_id] : !muted[part.part_id]
      gain.gain.setTargetAtTime(on ? 1 : 0, ctx.currentTime, 0.015)
    })
    if (masterRef.current) {
      masterRef.current.gain.setTargetAtTime(master, ctx.currentTime, 0.02)
    }
  }, [muted, solo, master, parts])

  // 卸载时收尾，避免音轨在切换曲目后继续响
  useEffect(
    () => () => {
      stopSources()
      ctxRef.current?.close().catch(() => undefined)
      ctxRef.current = null
      masterRef.current = null
      gainsRef.current.clear()
    },
    [stopSources],
  )

  const toggle = async () => {
    const ctx = ensureContext()
    if (!ctx) {
      setError('当前浏览器不支持 Web Audio')
      return
    }
    if (ctx.state === 'suspended') await ctx.resume()
    if (playing) {
      offsetRef.current = ctx.currentTime - anchorRef.current
      stopSources()
      setPlaying(false)
      return
    }
    startAt(offsetRef.current >= duration ? 0 : offsetRef.current)
  }

  const stop = () => {
    offsetRef.current = 0
    stopSources()
    setPlaying(false)
    setElapsed(0)
  }

  const seek = (event: React.MouseEvent<HTMLDivElement>) => {
    const bar = barRef.current
    if (!bar || duration <= 0) return
    const rect = bar.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    const target = ratio * duration
    offsetRef.current = target
    setElapsed(target)
    if (playing) startAt(target)
  }

  const toggleMute = (partId: string) =>
    setMuted((prev) => ({ ...prev, [partId]: !prev[partId] }))

  const toggleSolo = (partId: string) =>
    setSolo((prev) => ({ ...prev, [partId]: !prev[partId] }))

  if (error) {
    return (
      <div className="mix-panel mix-panel-error" role="alert">
        <strong>排练播放器不可用</strong>
        <span>{error}</span>
      </div>
    )
  }

  const progress = duration > 0 ? Math.min(100, (elapsed / duration) * 100) : 0
  const anySolo = parts.some((part) => solo[part.part_id])

  return (
    <div className="mix-panel" aria-label="声部排练播放器">
      <div className="mix-row mix-transport">
        <button
          type="button"
          className="mix-play"
          onClick={toggle}
          disabled={loading || !ready}
          aria-label={playing ? '暂停' : '播放'}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <button type="button" className="mix-stop" onClick={stop} disabled={!playing} aria-label="停止">
          ■
        </button>

        <div
          className="mix-track"
          ref={barRef}
          onClick={seek}
          role="presentation"
          title="点击跳转"
        >
          <div className="mix-progress" style={{ width: `${progress}%` }} />
        </div>

        <span className="mix-time">
          {formatClock(elapsed)} / {formatClock(duration)}
        </span>

        <label className="mix-master">
          <span>总音量</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={master}
            onChange={(event) => setMaster(Number(event.target.value))}
            aria-label="总音量"
          />
        </label>
      </div>

      <div className="mix-row mix-parts">
        <span className="mix-label">
          声部
          {loading && <em className="mix-loading">正在准备音频…</em>}
          {!loading && !ready && <em className="mix-loading">没有可用音轨</em>}
          {!loading && ready && <em className="mix-count">{playable.length} 条音轨</em>}
          {anySolo && <em className="mix-solo-note">独奏中</em>}
        </span>

        {parts.map((part) => {
          const own = isOwnPart(part)
          const silent = part.available ? !audible(part.part_id) : true
          return (
            <div
              key={part.part_id}
              className={`mix-chip${own ? ' own' : ''}${silent ? ' silent' : ''}`}
              style={{ '--part-color': roleColor(part) } as CSSProperties}
              title={part.available ? `${part.name} · ${part.note_count} 个音符` : `${part.name} 暂无音轨`}
            >
              <i className="mix-dot" />
              <span className="mix-name">{part.name}</span>
              {own && <em className="mix-own">我的</em>}
              <button
                type="button"
                className={`mix-btn${solo[part.part_id] ? ' on' : ''}`}
                onClick={() => toggleSolo(part.part_id)}
                disabled={!part.available}
                aria-pressed={Boolean(solo[part.part_id])}
                title="独奏：只播这个声部"
              >
                S
              </button>
              <button
                type="button"
                className={`mix-btn mix-btn-mute${muted[part.part_id] ? ' on' : ''}`}
                onClick={() => toggleMute(part.part_id)}
                disabled={!part.available}
                aria-pressed={Boolean(muted[part.part_id])}
                title="静音这个声部"
              >
                M
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
