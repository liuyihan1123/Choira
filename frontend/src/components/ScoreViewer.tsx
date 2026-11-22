import { useEffect, useRef, useState } from 'react'
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay'

interface Props {
  xml: string
  zoom: number
}

/** OSMD 封装：加载 MusicXML → 渲染为 SVG 页面。 */
export default function ScoreViewer({ xml, zoom }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const osmdRef = useRef<OpenSheetMusicDisplay | null>(null)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)

  useEffect(() => {
    const host = hostRef.current
    if (!host || !xml) return
    let cancelled = false
    setError('')
    setReady(false)
    host.innerHTML = ''

    const osmd = new OpenSheetMusicDisplay(host, {
      autoResize: true,
      backend: 'svg',
      drawTitle: true,
      drawComposer: true,
      drawCredits: false,
      drawPartNames: true,
      drawMeasureNumbers: true,
      pageBackgroundColor: '#ffffff',
    })
    osmdRef.current = osmd

    osmd
      .load(xml)
      .then(() => {
        if (cancelled) return
        osmd.Zoom = zoom
        osmd.render()
        setReady(true)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : '乐谱渲染失败')
      })

    return () => {
      cancelled = true
      try {
        ;(osmd as unknown as { dispose?: () => void }).dispose?.()
      } catch {
        /* 旧版本没有 dispose，忽略 */
      }
      osmdRef.current = null
      host.innerHTML = ''
    }
    // zoom 变化不应重新加载整份谱，单独在下面处理
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [xml])

  useEffect(() => {
    const osmd = osmdRef.current
    if (!osmd || !ready) return
    try {
      osmd.Zoom = zoom
      osmd.render()
    } catch {
      /* 渲染失败时保留上一帧 */
    }
  }, [zoom, ready])

  return (
    <div className="osmd-wrap">
      {!ready && !error && <div className="paper-status">正在排版…</div>}
      {error && (
        <div className="paper-status paper-error">
          <strong>渲染失败</strong>
          <span>{error}</span>
        </div>
      )}
      <div ref={hostRef} className="osmd-host" aria-label="乐谱" />
    </div>
  )
}
