import { clampRate, type StatusSegments } from '../statusModel'

function segmentGradient(segments: StatusSegments): string {
  if (!segments.total) return '#e2e8f0'
  let cursor = 0
  const parts: string[] = []
  const add = (count: number, color: string) => {
    if (count <= 0) return
    const start = (cursor / segments.total) * 100
    cursor += count
    const end = (cursor / segments.total) * 100
    parts.push(`${color} ${start.toFixed(2)}% ${end.toFixed(2)}%`)
  }
  add(segments.submitted, '#10b981')
  add(segments.late, '#0ea5e9')
  add(segments.invalid, '#f59e0b')
  add(segments.unmet, '#f43f5e')
  return `conic-gradient(${parts.join(', ') || '#e2e8f0 0% 100%'})`
}

export function StatusDonut({ rate, segments }: { rate: number; segments: StatusSegments }) {
  return (
    <div className="flex items-center justify-center">
      <div
        className="grid h-36 w-36 place-items-center rounded-full"
        style={{ background: segmentGradient(segments) }}
        aria-label={`提交率 ${(clampRate(rate) * 100).toFixed(2)}%`}
      >
        <div className="grid h-24 w-24 place-items-center rounded-full bg-white text-center">
          <span className="text-lg font-bold text-slate-900">{(clampRate(rate) * 100).toFixed(2)}%</span>
        </div>
      </div>
    </div>
  )
}

export function StatusProgressBar({ segments }: { segments: StatusSegments }) {
  if (!segments.total) return <div className="h-3 rounded-full bg-slate-200" />
  const width = (count: number) => `${((count / segments.total) * 100).toFixed(2)}%`
  return (
    <div className="flex h-3 overflow-hidden rounded-full bg-slate-200">
      <div className="bg-emerald-500" style={{ width: width(segments.submitted) }} />
      <div className="bg-sky-500" style={{ width: width(segments.late) }} />
      <div className="bg-amber-500" style={{ width: width(segments.invalid) }} />
      <div className="bg-rose-500" style={{ width: width(segments.unmet) }} />
    </div>
  )
}
