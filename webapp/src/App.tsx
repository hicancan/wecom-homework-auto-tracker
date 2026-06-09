import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  buildVersionedJsonUrl,
  type CourseIndex,
  type CourseItem,
  type CourseManifest,
  loadCourseIndex,
} from './courseIndexLoader'

type ClassStat = {
  应交人数: number
  截止已交人数?: number
  截止未达标人数?: number
  截止提交率?: number
  截止已交名单?: string[]
  截止未达标名单?: string[]
  已交人数: number
  未交人数: number
  提交率: number
  已交名单: string[]
  未交名单: string[]
  后缀格式无效人数?: number
  后缀格式无效名单?: string[]
  已补交人数?: number
  已补交名单?: string[]
}

type ContentStatPayload = {
  班级统计?: Record<string, ClassStat>
}

type ContentStatSummary = {
  提交内容: string
  应交人数: number
  已交人数: number
  未交人数: number
  后缀格式无效人数: number
  已补交人数: number
  提交率: number
}

type IssueSummary = {
  总人数: number
  班级统计?: Record<string, string[]>
  同步提示?: string
}

type SubmissionStat = {
  课程: string
  主题?: string
  对象?: string
  周期?: string
  状态?: 'active' | 'archived'
  提交序号: string
  提交内容列表?: string[]
  提交内容统计?: Record<string, ContentStatPayload> | ContentStatSummary[]
  更新时间?: string
  最后部署时间?: string
  最后提交时间?: string
  统计截止时间?: string
  后缀格式无效?: IssueSummary
  其他已交名单?: string[]
  其他后缀格式无效名单?: string[]
  其他已补交名单?: string[]
  汇总?: {
    应交总人数: number
    截止已交总人数?: number
    已补交总人数?: number
    已交总人数: number
    未交总人数: number
    总提交率: number
    后缀格式无效总人数?: number
  }
  班级统计: Record<string, ClassStat>
  补交状态?: Record<
    string,
    {
      已补交名单?: string[]
    }
  >
}

type CollectionSubmissionRef = {
  提交序号: string
  数据文件: string
  提交内容列表?: string[]
}

type CollectionIndex = {
  课程: string
  主题?: string
  对象?: string
  周期?: string
  状态?: 'active' | 'archived'
  更新时间?: string
  最后部署时间?: string
  提交序号列表: CollectionSubmissionRef[]
}

function clampRate(rate: number): number {
  if (Number.isNaN(rate)) return 0
  if (rate < 0) return 0
  if (rate > 1) return 1
  return rate
}

function extractStudentNo(raw: string): string {
  const text = String(raw).trim()
  const match = text.match(/^([A-Za-z]\d{6,}|\d{6,})(.*)$/)
  return match ? match[1] : text
}

function summarizeContentStats(value: SubmissionStat['提交内容统计']): ContentStatSummary[] {
  if (!value) return []
  if (Array.isArray(value)) return value

  return Object.entries(value).map(([content, payload]) => {
    const classStats = Object.values(payload.班级统计 || {})
    const totals = classStats.reduce(
      (acc, stat) => {
        acc.expected += stat.应交人数 || 0
        acc.submitted += stat.已交人数 || 0
        acc.missing += stat.未交人数 || 0
        acc.invalid += stat.后缀格式无效人数 || 0
        acc.late += stat.已补交人数 || 0
        return acc
      },
      { expected: 0, submitted: 0, missing: 0, invalid: 0, late: 0 },
    )
    return {
      提交内容: content,
      应交人数: totals.expected,
      已交人数: totals.submitted,
      未交人数: totals.missing,
      后缀格式无效人数: totals.invalid,
      已补交人数: totals.late,
      提交率: totals.expected ? totals.submitted / totals.expected : 0,
    }
  })
}

function safeDecodeURIComponent(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

function buildCoursePath(courseName: string): string {
  return `/course/${encodeURIComponent(courseName)}`
}

type OtherSubmissionRecord = {
  studentNo: string
  label: string
  className: string
}

type AttentionRecord = {
  studentNo: string
  label: string
  className: string
}

type StatusSegments = {
  onTime: number
  late: number
  invalid: number
  missing: number
  total: number
}

const STATUS_COLORS = {
  onTime: '#10b981',
  late: '#0ea5e9',
  invalid: '#f59e0b',
  missing: '#f43f5e',
}

function buildStatusSegments(expected: number, submitted: number, late: number, invalid: number): StatusSegments {
  const safeExpected = Math.max(0, expected || 0)
  const safeSubmitted = Math.max(0, Math.min(submitted || 0, safeExpected))
  const safeLate = Math.max(0, Math.min(late || 0, safeSubmitted))
  const safeInvalid = Math.max(0, Math.min(invalid || 0, safeExpected - safeSubmitted))
  return {
    onTime: safeSubmitted - safeLate,
    late: safeLate,
    invalid: safeInvalid,
    missing: Math.max(0, safeExpected - safeSubmitted - safeInvalid),
    total: safeExpected,
  }
}

function segmentGradient(segments: StatusSegments): string {
  const total = segments.total
  if (!total) return '#e2e8f0'
  const parts: string[] = []
  let cursor = 0
  const add = (count: number, color: string) => {
    if (count <= 0) return
    const next = cursor + (count / total) * 360
    parts.push(`${color} ${cursor.toFixed(2)}deg ${next.toFixed(2)}deg`)
    cursor = next
  }
  add(segments.onTime, STATUS_COLORS.onTime)
  add(segments.late, STATUS_COLORS.late)
  add(segments.invalid, STATUS_COLORS.invalid)
  add(segments.missing, STATUS_COLORS.missing)
  return `conic-gradient(${parts.join(', ')})`
}

function buildAttentionRecords(classStat: ClassStat): AttentionRecord[] {
  const records = new Map<string, AttentionRecord>()
  const add = (list: string[] | undefined, tone: { className: string; label: string }) => {
    for (const item of list || []) {
      const studentNo = extractStudentNo(item)
      records.set(studentNo, { studentNo, label: tone.label, className: tone.className })
    }
  }

  add(classStat.未交名单, { className: 'border-rose-200 bg-rose-50 text-rose-800', label: '未提交' })
  add(classStat.后缀格式无效名单, { className: 'border-amber-200 bg-amber-50 text-amber-800', label: '后缀格式无效' })
  add(classStat.已补交名单, { className: 'border-sky-200 bg-sky-50 text-sky-800', label: '补交' })

  return [...records.values()].sort((a, b) => a.studentNo.localeCompare(b.studentNo))
}

function buildOtherSubmissionRecords(stat: SubmissionStat | null): OtherSubmissionRecord[] {
  if (!stat) return []
  const records = new Map<string, OtherSubmissionRecord>()
  const add = (list: string[] | undefined, label: string, className: string) => {
    for (const item of list || []) {
      const studentNo = extractStudentNo(item)
      if (!records.has(studentNo)) {
        records.set(studentNo, { studentNo, label, className })
      }
    }
  }

  add(stat.其他已交名单, '已提交', 'border-emerald-200 bg-emerald-50 text-emerald-800')
  add(stat.其他已补交名单, '补交', 'border-sky-200 bg-sky-50 text-sky-800')
  add(stat.其他后缀格式无效名单, '后缀格式无效', 'border-amber-200 bg-amber-50 text-amber-800')

  return [...records.values()].sort((a, b) => a.studentNo.localeCompare(b.studentNo))
}

type DonutProps = {
  rate: number
  segments?: StatusSegments
  size?: number
  label?: string
  color?: string
}

type IconName = 'book' | 'hash' | 'clock' | 'list' | 'donut' | 'users' | 'warn' | 'trend' | 'share' | 'github' | 'home'

function AppIcon({ name, className = 'h-4 w-4' }: { name: IconName; className?: string }) {
  const common = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    viewBox: '0 0 24 24',
    className,
    'aria-hidden': true,
  }

  if (name === 'book') {
    return (
      <svg {...common}>
        <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 0 4 22z" />
        <path d="M4 5.5V22" />
      </svg>
    )
  }
  if (name === 'hash') {
    return (
      <svg {...common}>
        <path d="M9 3 7 21M17 3l-2 18M4 9h17M3 15h17" />
      </svg>
    )
  }
  if (name === 'clock') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    )
  }
  if (name === 'list') {
    return (
      <svg {...common}>
        <path d="M9 6h11M9 12h11M9 18h11" />
        <circle cx="4" cy="6" r="1" />
        <circle cx="4" cy="12" r="1" />
        <circle cx="4" cy="18" r="1" />
      </svg>
    )
  }
  if (name === 'donut') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 4a8 8 0 0 1 8 8" />
      </svg>
    )
  }
  if (name === 'users') {
    return (
      <svg {...common}>
        <path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
        <circle cx="9.5" cy="8" r="3" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a3 3 0 0 1 0 5.74" />
      </svg>
    )
  }
  if (name === 'warn') {
    return (
      <svg {...common}>
        <path d="M12 3 2.5 20h19z" />
        <path d="M12 9v5M12 17h.01" />
      </svg>
    )
  }
  if (name === 'share') {
    return (
      <svg {...common}>
        <path d="M8.5 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z" />
        <path d="M15.5 19a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z" />
        <path d="M8 9.5l7 5" />
      </svg>
    )
  }
  if (name === 'github') {
    return (
      <svg {...common}>
        <path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.21.68-.48v-1.69c-2.78.61-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.48-1.11-1.48-.91-.62.07-.61.07-.61 1.01.07 1.54 1.04 1.54 1.04.89 1.54 2.34 1.09 2.91.84.09-.65.35-1.09.63-1.34-2.22-.26-4.56-1.12-4.56-4.96 0-1.1.39-2 1.03-2.7-.1-.25-.45-1.29.1-2.67 0 0 .84-.27 2.75 1.03A9.55 9.55 0 0 1 12 6.84c.85 0 1.71.12 2.51.36 1.9-1.3 2.75-1.03 2.75-1.03.55 1.38.2 2.42.1 2.67.64.7 1.03 1.6 1.03 2.7 0 3.85-2.34 4.7-4.57 4.96.36.31.67.91.67 1.84v2.73c0 .27.18.58.69.48A10 10 0 0 0 12 2z" />
      </svg>
    )
  }
  if (name === 'home') {
    return (
      <svg {...common}>
        <path d="M3 11.5 12 4l9 7.5" />
        <path d="M5 10.5V20h14v-9.5" />
        <path d="M10 20v-5h4v5" />
      </svg>
    )
  }
  return (
    <svg {...common}>
      <path d="M3 17 9 11l4 4 8-8" />
      <path d="M14 7h7v7" />
    </svg>
  )
}

function DonutChart({ rate, segments, size = 116, label, color = '#0284c7' }: DonutProps) {
  const r = clampRate(rate)
  const degree = Math.round(r * 360)
  const value = `${(r * 100).toFixed(2)}%`
  const background = segments ? segmentGradient(segments) : `conic-gradient(${color} 0 ${degree}deg, #e2e8f0 ${degree}deg 360deg)`

  return (
    <div className="inline-flex flex-col items-center justify-center gap-2">
      <div
        className="relative rounded-full"
        style={{
          width: `${size}px`,
          height: `${size}px`,
          background,
        }}
      >
        <div
          className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white text-xs font-semibold text-slate-700"
          style={{ width: `${size * 0.66}px`, height: `${size * 0.66}px` }}
        >
          {value}
        </div>
      </div>
      {label && <p className="text-xs text-slate-500 text-center">{label}</p>}
    </div>
  )
}

function StatusProgressBar({ segments }: { segments: StatusSegments }) {
  if (!segments.total) {
    return <div className="mt-3 h-2 w-full rounded-full bg-slate-200" />
  }
  const width = (count: number) => `${((count / segments.total) * 100).toFixed(2)}%`
  return (
    <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-slate-100">
      <div className="h-full bg-emerald-500" style={{ width: width(segments.onTime) }} />
      <div className="h-full bg-sky-500" style={{ width: width(segments.late) }} />
      <div className="h-full bg-amber-500" style={{ width: width(segments.invalid) }} />
      <div className="h-full bg-rose-500" style={{ width: width(segments.missing) }} />
    </div>
  )
}

function StatusLegend() {
  const items = [
    ['已提交', 'bg-emerald-500'],
    ['补交', 'bg-sky-500'],
    ['后缀格式无效', 'bg-amber-500'],
    ['未提交', 'bg-rose-500'],
  ] as const
  return (
    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
      {items.map(([label, colorClass]) => (
        <span key={label} className="inline-flex items-center gap-1">
          <span className={`h-2 w-2 rounded-full ${colorClass}`} />
          {label}
        </span>
      ))}
    </div>
  )
}

function App() {
  const navigate = useNavigate()
  const { courseName = '' } = useParams()
  const [searchParams] = useSearchParams()
  const routeCourse = safeDecodeURIComponent(courseName)
  const routeSubmission = safeDecodeURIComponent(searchParams.get('seq') || '')
  const hasLegacySubmissionParam = searchParams.has('hw')
  const publicBase = import.meta.env.BASE_URL || '/'

  const [manifestData, setManifestData] = useState<CourseManifest | null>(null)
  const [indexData, setIndexData] = useState<CourseIndex | null>(null)
  const [collectionIndex, setCollectionIndex] = useState<CollectionIndex | null>(null)
  const [selectedSubmissionData, setSelectedSubmissionData] = useState<SubmissionStat | null>(null)
  const [isCourseLoading, setIsCourseLoading] = useState(false)
  const [isSubmissionLoading, setIsSubmissionLoading] = useState(false)
  const [shareFeedback, setShareFeedback] = useState('')
  const [indexError, setIndexError] = useState('')
  const [courseError, setCourseError] = useState('')

  useEffect(() => {
    if (!shareFeedback) return
    const timer = window.setTimeout(() => setShareFeedback(''), 2200)
    return () => window.clearTimeout(timer)
  }, [shareFeedback])

  useEffect(() => {
    let active = true
    loadCourseIndex(publicBase)
      .then(({ manifest, index }) => {
        if (!active) return
        setManifestData(manifest)
        setIndexData(index)
        setIndexError('')
      })
      .catch((e: unknown) => {
        if (!active) return
        setManifestData(null)
        setIndexData(null)
        setIndexError(e instanceof Error ? e.message : '加载失败')
      })
    return () => {
      active = false
    }
  }, [publicBase])

  const courseMap = useMemo(() => {
    const map = new Map<string, CourseItem>()
    for (const item of indexData?.课程列表 || []) {
      map.set(item.课程, item)
    }
    return map
  }, [indexData])

  const selectedCourse = useMemo(() => {
    if (!indexData || !routeCourse || !courseMap.has(routeCourse)) return ''
    return routeCourse
  }, [courseMap, indexData, routeCourse])

  const selectedCourseItem = useMemo(() => {
    if (!selectedCourse) return null
    return courseMap.get(selectedCourse) || null
  }, [courseMap, selectedCourse])

  useEffect(() => {
    if (!selectedCourse) {
      setCollectionIndex(null)
      setSelectedSubmissionData(null)
      setCourseError('')
      setIsCourseLoading(false)
      setIsSubmissionLoading(false)
      return
    }

    const item = courseMap.get(selectedCourse)
    if (!item) return

    const controller = new AbortController()
    setIsCourseLoading(true)
    setCollectionIndex(null)
    setSelectedSubmissionData(null)
    setCourseError('')

    fetch(buildVersionedJsonUrl(publicBase, item.数据文件, manifestData?.version), { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        return res.json() as Promise<CollectionIndex>
      })
      .then((json) => {
        if (controller.signal.aborted) return
        setCollectionIndex(json)
        setIsCourseLoading(false)
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return
        setCollectionIndex(null)
        setSelectedSubmissionData(null)
        setCourseError(e instanceof Error ? e.message : '收集表数据加载失败')
        setIsCourseLoading(false)
      })

    return () => controller.abort()
  }, [courseMap, manifestData?.version, publicBase, selectedCourse])

  const submissionMap = useMemo(() => {
    const map = new Map<string, CollectionSubmissionRef>()
    for (const item of collectionIndex?.提交序号列表 || []) {
      map.set(item.提交序号, item)
    }
    return map
  }, [collectionIndex])

  const submissionKeys = useMemo(() => {
    const keys: string[] = []
    const seen = new Set<string>()
    for (const item of collectionIndex?.提交序号列表 || []) {
      if (seen.has(item.提交序号)) continue
      seen.add(item.提交序号)
      keys.push(item.提交序号)
    }
    return keys
  }, [collectionIndex])

  const selectedKey = useMemo(() => {
    if (!submissionKeys.length) return ''
    if (routeSubmission && submissionKeys.includes(routeSubmission)) {
      return routeSubmission
    }
    return submissionKeys[submissionKeys.length - 1]
  }, [submissionKeys, routeSubmission])

  useEffect(() => {
    if (!selectedCourse || !selectedKey) {
      setSelectedSubmissionData(null)
      setIsSubmissionLoading(false)
      return
    }

    const submissionRef = submissionMap.get(selectedKey)
    if (!submissionRef) {
      setSelectedSubmissionData(null)
      setIsSubmissionLoading(false)
      return
    }

    const controller = new AbortController()
    setIsSubmissionLoading(true)
    setSelectedSubmissionData(null)
    setCourseError('')

    fetch(buildVersionedJsonUrl(publicBase, submissionRef.数据文件, manifestData?.version), {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        return res.json() as Promise<SubmissionStat>
      })
      .then((json) => {
        if (controller.signal.aborted) return
        setSelectedSubmissionData(json)
        setIsSubmissionLoading(false)
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return
        setSelectedSubmissionData(null)
        setCourseError(e instanceof Error ? e.message : '提交数据加载失败')
        setIsSubmissionLoading(false)
      })

    return () => controller.abort()
  }, [manifestData?.version, publicBase, selectedCourse, selectedKey, submissionMap])

  useEffect(() => {
    if (!selectedCourse || !collectionIndex || collectionIndex.课程 !== selectedCourse || hasLegacySubmissionParam) return
    const nextPathname = buildCoursePath(selectedCourse)
    const nextSearchParams = new URLSearchParams()
    if (selectedKey) {
      nextSearchParams.set('seq', selectedKey)
    }
    const nextSearch = nextSearchParams.toString()
    const currentSubmission = routeSubmission || ''

    if (routeCourse !== selectedCourse || currentSubmission !== selectedKey || searchParams.toString() !== nextSearch) {
      navigate(
        {
          pathname: nextPathname,
          search: nextSearch ? `?${nextSearch}` : '',
        },
        { replace: true },
      )
    }
  }, [collectionIndex, hasLegacySubmissionParam, navigate, routeCourse, routeSubmission, searchParams, selectedCourse, selectedKey])

  const routeError = useMemo(() => {
    if (!indexData) return ''
    if (!routeCourse) return '路由缺少收集表参数，请使用分享链接进入。'
    if (!courseMap.has(routeCourse)) return `收集表参数无效：${routeCourse}`
    if (hasLegacySubmissionParam) return '旧 hw 参数已无效，请使用 seq 参数访问提交序号。'
    if (routeSubmission && collectionIndex && !submissionMap.has(routeSubmission)) {
      return `提交序号参数无效：${routeSubmission}`
    }
    return ''
  }, [collectionIndex, courseMap, hasLegacySubmissionParam, indexData, routeCourse, routeSubmission, submissionMap])

  const error = indexError || courseError

  async function handleShareLink() {
    if (!selectedCourse || routeError) return
    const url = window.location.href
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error('clipboard unavailable')
      }
      await navigator.clipboard.writeText(url)
      setShareFeedback('分享链接已复制')
    } catch {
      setShareFeedback('复制失败，请手动复制地址栏链接')
    }
  }

  const selected = routeError ? null : selectedSubmissionData
  const selectedSubmissionRef = !routeError && selectedKey ? submissionMap.get(selectedKey) || null : null
  const selectedContentList = selected?.提交内容列表?.length
    ? selected.提交内容列表
    : selectedSubmissionRef?.提交内容列表 || []
  const contentSummaries = useMemo(() => summarizeContentStats(selected?.提交内容统计), [selected])

  const courseList = useMemo(() => {
    if (!indexData) return []
    return indexData.课程列表 || []
  }, [indexData])

  const classEntries = useMemo(() => {
    if (!selected) return [] as Array<[string, ClassStat]>
    return Object.entries(selected.班级统计).sort(([a], [b]) => a.localeCompare(b))
  }, [selected])

  const otherSubmissionRecords = useMemo(() => buildOtherSubmissionRecords(selected), [selected])

  const aggregate = useMemo(() => {
    return classEntries.reduce(
      (acc, [, stat]) => {
        acc.expected += stat.应交人数
        acc.submitted += stat.已交人数
        acc.missing += stat.未交人数
        acc.late += stat.已补交人数 || 0
        acc.invalid += stat.后缀格式无效人数 || 0
        return acc
      },
      { expected: 0, submitted: 0, missing: 0, late: 0, invalid: 0 },
    )
  }, [classEntries])

  const aggregateRate = aggregate.expected ? aggregate.submitted / aggregate.expected : 0
  const summaryExpected = aggregate.expected
  const summarySubmitted = aggregate.submitted
  const summaryMissing = aggregate.missing
  const summaryRate = aggregateRate
  const summarySegments = buildStatusSegments(summaryExpected, summarySubmitted, aggregate.late, aggregate.invalid)
  const courseTopic = selectedCourseItem?.主题 || collectionIndex?.主题 || selectedSubmissionData?.主题 || '提交追踪看板'
  const courseAudience = selectedCourseItem?.对象 || collectionIndex?.对象 || selectedSubmissionData?.对象 || ''
  const coursePeriod = selectedCourseItem?.周期 || collectionIndex?.周期 || selectedSubmissionData?.周期 || ''
  const courseStatus = selectedCourseItem?.状态 || collectionIndex?.状态 || selectedSubmissionData?.状态 || 'active'
  const isArchivedCourse = courseStatus === 'archived'
  const hasCourseMeta = !!selectedCourseItem || !!collectionIndex || !!selectedSubmissionData

  const deployTime =
    selectedSubmissionData?.最后部署时间 ||
    collectionIndex?.最后部署时间 ||
    manifestData?.最后部署时间 ||
    indexData?.最后部署时间 ||
    selectedSubmissionData?.更新时间 ||
    collectionIndex?.更新时间 ||
    manifestData?.更新时间 ||
    indexData?.更新时间 ||
    '加载中...'

  const canInteract = !routeError && !!selectedCourse && !!collectionIndex

  return (
    <main className="min-h-screen text-slate-900">
      <div className="mx-auto max-w-7xl px-4 py-8 md:px-6 md:py-12">
        <header className="animate-rise rounded-lg border border-slate-200 bg-white p-6 shadow-sm md:p-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              {hasCourseMeta && (
                <div className="flex flex-wrap items-center gap-2">
                  {courseAudience && (
                    <span className="rounded-full bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700">
                      {courseAudience}
                    </span>
                  )}
                  {coursePeriod && (
                    <span className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700">
                      {coursePeriod}
                    </span>
                  )}
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                      isArchivedCourse ? 'bg-slate-100 text-slate-600' : 'bg-emerald-50 text-emerald-700'
                    }`}
                  >
                    {isArchivedCourse ? '已归档' : '进行中'}
                  </span>
                </div>
              )}
              <h1 className="mt-3 break-words text-2xl font-bold text-slate-900 md:text-4xl">{courseTopic}</h1>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap sm:justify-end">
              <button
                type="button"
                onClick={handleShareLink}
                disabled={!canInteract}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-medium text-sky-800 transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
              >
                <AppIcon name="share" className="h-4 w-4" />
                分享当前收集表链接
              </button>
              <a
                href="https://homework.hicancan.top/"
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-800 transition hover:bg-emerald-100 sm:w-auto"
                aria-label="返回主页"
              >
                <AppIcon name="home" className="h-4 w-4" />
                返回主页
              </a>
              <a
                href="https://github.com/hicancan/wecom-homework-auto-tracker"
                target="_blank"
                rel="noreferrer"
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 sm:w-auto"
                aria-label="GitHub 仓库"
              >
                <AppIcon name="github" className="h-4 w-4" />
                GitHub
              </a>
            </div>
          </div>
          <p className="mt-3 text-sm text-slate-600">
            网页最后部署时间：{deployTime}
          </p>
          {shareFeedback && <p className="mt-2 text-xs text-slate-500">{shareFeedback}</p>}
        </header>

        <section className="animate-rise-delayed mt-6 rounded-3xl border border-sky-100 bg-white/90 p-4 shadow-[0_20px_60px_rgba(2,132,199,0.12)] backdrop-blur md:p-5">
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="mb-2 flex items-center gap-2 text-sm text-slate-700" htmlFor="course-select">
                <AppIcon name="book" className="h-4 w-4 text-sky-700" />
                收集表
              </label>
              <select
                id="course-select"
                className="w-full rounded-xl border border-sky-200 bg-white px-3 py-2 text-sm outline-none ring-sky-300 transition focus:ring"
                value={selectedCourse}
                onChange={(e) => {
                  const nextCourse = e.target.value
                  navigate({ pathname: buildCoursePath(nextCourse), search: '' }, { replace: false })
                }}
                disabled={!courseList.length}
              >
                {!selectedCourse && <option value="">请选择收集表</option>}
                {courseList.map((course) => (
                  <option key={course.课程} value={course.课程}>
                    {course.主题}[{course.对象}]{course.周期 ? `[${course.周期}]` : ''}
                    {course.状态 === 'archived' ? ' - 已归档' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-2 flex items-center gap-2 text-sm text-slate-700" htmlFor="submission-select">
                <AppIcon name="hash" className="h-4 w-4 text-indigo-700" />
                提交序号
              </label>
              <select
                id="submission-select"
                className="w-full rounded-xl border border-sky-200 bg-white px-3 py-2 text-sm outline-none ring-sky-300 transition focus:ring"
                value={selectedKey}
                onChange={(e) => {
                  const nextSubmission = e.target.value
                  const nextSearchParams = new URLSearchParams()
                  if (nextSubmission) {
                    nextSearchParams.set('seq', nextSubmission)
                  }
                  const nextSearch = nextSearchParams.toString()
                  navigate(
                    { pathname: buildCoursePath(selectedCourse), search: nextSearch ? `?${nextSearch}` : '' },
                    { replace: false },
                  )
                }}
                disabled={!submissionKeys.length || !canInteract}
              >
                {isCourseLoading && <option value="">加载中...</option>}
                {!isCourseLoading && !selectedKey && <option value="">请选择提交序号</option>}
                {submissionKeys.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {!!selectedContentList.length && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white p-3">
              <div className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-600">
                <AppIcon name="list" className="h-4 w-4 text-slate-600" />
                提交内容
              </div>
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {selectedContentList.map((content) => {
                  const summary = contentSummaries.find((item) => item.提交内容 === content)
                  return (
                    <div key={content} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
                      <p className="break-all text-sm font-medium text-slate-800">{content}</p>
                      {summary &&
                        (selectedContentList.length > 1 ||
                          !!summary.后缀格式无效人数 ||
                          !!summary.已补交人数) && (
                        <p className="mt-1 text-xs text-slate-500">
                          {[
                            selectedContentList.length > 1 ? `最终提交 ${summary.已交人数} / 应交 ${summary.应交人数}` : '',
                            summary.已补交人数 ? `补交 ${summary.已补交人数} 人` : '',
                            summary.后缀格式无效人数 ? `后缀格式无效 ${summary.后缀格式无效人数} 人` : '',
                          ]
                            .filter(Boolean)
                            .join('，')}
                        </p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {selected && (
            <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
              <div className="grid content-start gap-3">
                <div className="rounded-xl border border-sky-100 bg-sky-50/70 p-4">
                  <p className="flex items-center gap-2 text-xs text-slate-500">
                    <AppIcon name="clock" className="h-4 w-4 text-sky-700" />
                    当前提交序号统计截止时间
                  </p>
                  <p className="mt-1 text-xl font-semibold tracking-tight text-sky-700">
                    {selected.统计截止时间 || selected.最后提交时间 || '-'}
                  </p>
                </div>
                <div className="rounded-xl border border-emerald-100 bg-emerald-50/70 p-4">
                  <p className="flex items-center gap-2 text-xs text-slate-500">
                    <AppIcon name="list" className="h-4 w-4 text-emerald-700" />
                    应交 / 最终提交 / 未提交
                  </p>
                  <p className="mt-1 text-xl font-semibold tracking-tight text-slate-800">
                    {summaryExpected} / {summarySubmitted} / {summaryMissing}
                  </p>
                  <StatusProgressBar segments={summarySegments} />
                  <StatusLegend />
                  <p className="mt-2 text-xs text-emerald-700">最终提交率 {(summaryRate * 100).toFixed(2)}%</p>
                </div>
              </div>
              <div className="rounded-xl border border-indigo-100 bg-indigo-50/60 p-4 lg:sticky lg:top-4">
                <p className="flex items-center gap-2 text-xs text-slate-500">
                  <AppIcon name="donut" className="h-4 w-4 text-indigo-700" />
                  当前提交序号最终提交率
                </p>
                <div className="mt-3 flex items-center justify-center">
                  <DonutChart
                    rate={summaryRate}
                    segments={summarySegments}
                    size={148}
                    label="最终提交构成"
                    color="#0ea5e9"
                  />
                </div>
              </div>
            </div>
          )}
        </section>

        {error && (
          <section className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            数据加载失败：{error}
          </section>
        )}

        {routeError && (
          <section className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
            路由参数错误：{routeError}
          </section>
        )}

        <section className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-4">
          {selected &&
            classEntries.map(([className, classStat]) => {
              const classSegments = buildStatusSegments(
                classStat.应交人数,
                classStat.已交人数,
                classStat.已补交人数 || 0,
                classStat.后缀格式无效人数 || 0,
              )
              const attentionRecords = buildAttentionRecords(classStat)
              return (
                <article key={className} className="animate-rise rounded-2xl border border-sky-100 bg-white/95 p-4 shadow-[0_20px_45px_rgba(14,165,233,0.1)] backdrop-blur">
                  <div className="mb-3 flex items-end justify-between border-b border-slate-100 pb-2">
                    <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
                      <AppIcon name="users" className="h-5 w-5 text-sky-700" />
                      {className}
                    </h2>
                    <p className="flex items-center gap-1 text-xs text-slate-500">
                      <AppIcon name="warn" className="h-3.5 w-3.5 text-amber-600" />
                      未提交 {classSegments.missing} / 应交 {classStat.应交人数}
                    </p>
                  </div>
                  <div className="mb-3 flex items-center justify-between rounded-xl border border-sky-100 bg-sky-50/50 p-2">
                    <DonutChart rate={classStat.提交率} segments={classSegments} size={78} label={`${className} 最终提交构成`} color="#14b8a6" />
                    <div className="text-right">
                      <p className="flex items-center justify-end gap-1 text-xs text-slate-500">
                        <AppIcon name="trend" className="h-3.5 w-3.5 text-teal-700" />
                        班级最终提交率
                      </p>
                      <p className="text-base font-semibold text-teal-700">{(classStat.提交率 * 100).toFixed(2)}%</p>
                    </div>
                  </div>
                  <p className="mb-2 text-center text-xs font-medium text-slate-500">补交与异常名单</p>
                  <ul className="space-y-2 text-sm">
                    {attentionRecords.length ? (
                      attentionRecords.map((record) => (
                        <li
                          key={record.studentNo}
                          className={`flex items-center justify-between gap-2 rounded-lg border px-2 py-1 text-xs ${record.className}`}
                        >
                          <span className="font-medium">{record.studentNo}</span>
                          <span>{record.label}</span>
                        </li>
                      ))
                    ) : (
                      <li className="rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-center text-emerald-700">
                        本班全部截止前有效提交
                      </li>
                    )}
                  </ul>
                </article>
              )
            })}

          {!selected && !error && !routeError && collectionIndex && !isSubmissionLoading && (
            <article className="col-span-full animate-rise rounded-2xl border border-slate-200 bg-white/95 p-6 text-center text-slate-600 shadow-[0_20px_45px_rgba(14,165,233,0.08)]">
              当前收集表暂无提交数据
            </article>
          )}
        </section>

        {selected && (
          <section className="mt-6 rounded-2xl border border-emerald-200 bg-white/95 p-5 shadow-[0_20px_45px_rgba(16,185,129,0.1)]">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h3 className="text-base font-semibold text-slate-900">其他（重修/补修）提交记录</h3>
              <span className="text-xs text-emerald-700">记录 {otherSubmissionRecords.length} 人</span>
            </div>
            {otherSubmissionRecords.length ? (
              <ul className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-2 text-sm">
                {otherSubmissionRecords.map((record) => (
                  <li
                    key={record.studentNo}
                    className={`flex items-center justify-between gap-2 rounded-lg border px-2 py-1 text-xs ${record.className}`}
                  >
                    <span className="font-medium">{record.studentNo}</span>
                    <span>{record.label}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-center text-sm text-slate-600">
                当前提交序号暂无“其他”同学提交记录
              </p>
            )}
          </section>
        )}
      </div>
    </main>
  )
}

export default App
