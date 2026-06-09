import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { loadCollectionIndex, loadCollectionRoot, loadSubmissionStat } from '../api'
import { ClassStatusCard, OtherStatusCard } from '../components/ClassStatusCard'
import { ContentSummary } from '../components/ContentSummary'
import { StatusDonut, StatusProgressBar } from '../components/StatusChart'
import { StatusLegend } from '../components/StatusLegend'
import { summarizeContentStats } from '../contentModel'
import { buildStatusSegments } from '../statusModel'
import type { CollectionIndex, CollectionItem, CollectionManifest, CollectionRoot, SubmissionStat } from '../types'

const HOME_PAGE_URL = 'https://homework.hicancan.top/'

export function CollectionPage() {
  const { collectionId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const publicBase = import.meta.env.BASE_URL || '/'
  const [rootData, setRootData] = useState<CollectionRoot | null>(null)
  const [manifestData, setManifestData] = useState<CollectionManifest | null>(null)
  const [collectionIndex, setCollectionIndex] = useState<CollectionIndex | null>(null)
  const [submissionData, setSubmissionData] = useState<SubmissionStat | null>(null)
  const [rootError, setRootError] = useState('')
  const [pageError, setPageError] = useState('')
  const hasLegacySubmissionParam = searchParams.has('hw')
  const routeSeq = searchParams.get('seq') || ''

  useEffect(() => {
    let active = true
    loadCollectionRoot(publicBase)
      .then(({ manifest, index }) => {
        if (!active) return
        setManifestData(manifest)
        setRootData(index)
        setRootError('')
      })
      .catch((e: unknown) => {
        if (!active) return
        setManifestData(null)
        setRootData(null)
        setRootError(e instanceof Error ? e.message : '加载失败')
      })
    return () => {
      active = false
    }
  }, [publicBase])

  const collectionMap = useMemo(() => {
    const map = new Map<string, CollectionItem>()
    for (const item of rootData?.收集表列表 || []) {
      map.set(item.收集表ID, item)
    }
    return map
  }, [rootData])

  const selectedCollection = collectionMap.get(collectionId)

  useEffect(() => {
    if (!selectedCollection || hasLegacySubmissionParam) {
      setCollectionIndex(null)
      setSubmissionData(null)
      return
    }
    let active = true
    setPageError('')
    loadCollectionIndex(publicBase, selectedCollection.数据文件, manifestData?.version)
      .then((data) => {
        if (!active) return
        setCollectionIndex(data)
      })
      .catch((e: unknown) => {
        if (!active) return
        setCollectionIndex(null)
        setSubmissionData(null)
        setPageError(e instanceof Error ? e.message : '加载失败')
      })
    return () => {
      active = false
    }
  }, [hasLegacySubmissionParam, manifestData?.version, publicBase, selectedCollection])

  const submissionMap = useMemo(() => {
    const map = new Map<string, NonNullable<CollectionIndex['提交序号列表']>[number]>()
    for (const item of collectionIndex?.提交序号列表 || []) {
      map.set(item.提交序号ID, item)
    }
    return map
  }, [collectionIndex])

  const selectedSeq = routeSeq || collectionIndex?.提交序号列表[collectionIndex.提交序号列表.length - 1]?.提交序号ID || ''
  const selectedRef = submissionMap.get(selectedSeq)

  useEffect(() => {
    if (!selectedCollection || !collectionIndex || hasLegacySubmissionParam) return
    const latestSeq = collectionIndex.提交序号列表[collectionIndex.提交序号列表.length - 1]?.提交序号ID
    if (!latestSeq) return
    const needRedirect = !routeSeq || !submissionMap.has(routeSeq)
    if (needRedirect) {
      navigate(`/collection/${encodeURIComponent(selectedCollection.收集表ID)}?seq=${encodeURIComponent(latestSeq)}`, { replace: true })
    }
  }, [collectionIndex, hasLegacySubmissionParam, navigate, routeSeq, selectedCollection, submissionMap])

  useEffect(() => {
    if (!selectedRef || hasLegacySubmissionParam) {
      setSubmissionData(null)
      return
    }
    let active = true
    setPageError('')
    loadSubmissionStat(publicBase, selectedRef.数据文件, manifestData?.version)
      .then((data) => {
        if (!active) return
        setSubmissionData(data)
      })
      .catch((e: unknown) => {
        if (!active) return
        setSubmissionData(null)
        setPageError(e instanceof Error ? e.message : '加载失败')
      })
    return () => {
      active = false
    }
  }, [hasLegacySubmissionParam, manifestData?.version, publicBase, selectedRef])

  const [shareLabel, setShareLabel] = useState('分享主页')
  async function handleShareLink() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
      await navigator.clipboard.writeText(window.location.href)
      setShareLabel('已复制!')
    } catch {
      setShareLabel('复制失败')
    }
    window.setTimeout(() => setShareLabel('分享主页'), 1800)
  }

  function handleCollectionChange(nextId: string) {
    setCollectionIndex(null)
    setSubmissionData(null)
    setPageError('')
    navigate(`/collection/${encodeURIComponent(nextId)}`)
  }

  function handleSeqChange(nextSeq: string) {
    navigate(`/collection/${encodeURIComponent(collectionId)}?seq=${encodeURIComponent(nextSeq)}`)
  }

  const invalidMessage = useMemo(() => {
    if (rootError) return rootError
    if (hasLegacySubmissionParam) return '旧 hw 参数已无效，请使用 seq 参数访问提交序号。'
    if (rootData && !selectedCollection) return `收集表 ID 无效：${collectionId}`
    if (collectionIndex && routeSeq && !submissionMap.has(routeSeq)) return `提交序号参数无效：${routeSeq}`
    if (pageError) return pageError
    return ''
  }, [collectionId, collectionIndex, hasLegacySubmissionParam, pageError, rootData, rootError, routeSeq, selectedCollection, submissionMap])

  const selectedContentList = submissionData?.提交内容列表?.length
    ? submissionData.提交内容列表
    : selectedRef?.提交内容列表 || []
  const contentSummaries = useMemo(() => summarizeContentStats(submissionData?.提交内容统计), [submissionData])
  const collections = rootData?.收集表列表 || []
  const classEntries = useMemo(() => {
    if (!submissionData) return []
    return Object.entries(submissionData.班级统计).sort(([a], [b]) => a.localeCompare(b))
  }, [submissionData])
  const summary = submissionData?.汇总
  const allowMakeup = submissionData?.允许补交 === true
  const expected = summary?.应交总人数 || 0
  const submitted = summary?.已提交总人数 || 0
  const late = allowMakeup ? summary?.已补交总人数 || 0 : 0
  const invalid = summary?.后缀无效总人数 || 0
  const rate = summary?.总提交率 || 0
  const segments = buildStatusSegments(expected, submitted, late, invalid)
  const status = selectedCollection?.状态 || collectionIndex?.状态 || submissionData?.状态 || 'active'
  const deployTime =
    manifestData?.最后部署时间 ||
    rootData?.最后部署时间 ||
    collectionIndex?.最后部署时间 ||
    submissionData?.最后部署时间 ||
    manifestData?.更新时间 ||
    rootData?.更新时间 ||
    '加载中...'

  return (
    <main className="min-h-screen bg-slate-100 text-slate-900">
      <div className="mx-auto max-w-[1600px] px-4 py-8 md:px-8">
        <header className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm md:p-7">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap gap-2 text-xs font-semibold">
                <span className="rounded-full bg-sky-100 px-3 py-1 text-sky-800">{selectedCollection?.对象 || collectionIndex?.对象 || '-'}</span>
                <span className="rounded-full bg-indigo-100 px-3 py-1 text-indigo-800">{selectedCollection?.周期 || collectionIndex?.周期 || '未分组'}</span>
                <span className={`rounded-full px-3 py-1 ${status === 'archived' ? 'bg-slate-200 text-slate-600' : 'bg-emerald-100 text-emerald-700'}`}>
                  {status === 'archived' ? '已归档' : '进行中'}
                </span>
              </div>
              <h1 className="mt-4 text-3xl font-bold md:text-5xl">{selectedCollection?.主题 || collectionIndex?.主题 || '收集表'}</h1>
              <p className="mt-3 text-sm text-slate-500">网页最后部署时间： {deployTime}</p>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <button
                type="button"
                onClick={handleShareLink}
                className="inline-flex items-center justify-center rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-800 transition-colors hover:bg-sky-100"
              >
                {shareLabel}
              </button>
              <Link className="inline-flex items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-100" to="/">
                返回主页
              </Link>
              <a className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-100" href="https://github.com/hicancan/wecom-homework-auto-tracker" target="_blank" rel="noreferrer">
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
                GitHub
              </a>
            </div>
          </div>
        </header>

        {invalidMessage ? (
          <section className="mt-6 rounded-lg border border-rose-200 bg-white p-5 text-rose-700 shadow-sm">
            <h2 className="text-lg font-semibold">参数无效</h2>
            <p className="mt-2 text-sm">{invalidMessage}</p>
            <a className="mt-4 inline-flex text-sm font-semibold text-sky-700" href={HOME_PAGE_URL}>
              返回主页
            </a>
          </section>
        ) : (
          <div className="mt-6 space-y-5">
            <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
              <div className="grid gap-4 md:grid-cols-2">
                <label className="text-sm font-semibold text-slate-700">
                  收集表
                  <select
                    className="mt-2 w-full rounded-md border border-sky-200 bg-white px-3 py-2 text-base text-slate-900 outline-none focus:border-sky-500"
                    value={collectionId}
                    onChange={(event) => handleCollectionChange(event.target.value)}
                  >
                    {collections.map((item) => (
                      <option key={item.收集表ID} value={item.收集表ID}>
                        {item.主题} [{item.对象}]
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-sm font-semibold text-slate-700">
                  提交序号
                  <select
                    className="mt-2 w-full rounded-md border border-sky-200 bg-white px-3 py-2 text-base text-slate-900 outline-none focus:border-sky-500"
                    value={selectedSeq}
                    onChange={(event) => handleSeqChange(event.target.value)}
                  >
                    {collectionIndex?.提交序号列表.map((item) => (
                      <option key={item.提交序号ID} value={item.提交序号ID}>
                        {item.提交序号}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <StatusLegend allowMakeup={allowMakeup} />
                <div className="flex flex-wrap items-center justify-start gap-2 text-sm md:justify-end">
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 font-semibold text-slate-700">
                    统计截止 {submissionData?.统计截止时间 || '加载中...'}
                  </span>
                  <span
                    className={`rounded-full border px-3 py-1 font-semibold ${
                      allowMakeup
                        ? 'border-sky-200 bg-sky-50 text-sky-800'
                        : 'border-slate-200 bg-slate-100 text-slate-700'
                    }`}
                  >
                    {allowMakeup ? '补交窗口' : '不允许补交'}
                  </span>
                  {allowMakeup && (
                    <span className="rounded-full border border-sky-200 bg-white px-3 py-1 font-semibold text-sky-800">
                      {(submissionData?.补交窗口开始时间 || submissionData?.统计截止时间 || '-')} 至 {submissionData?.补交窗口结束时间 || '-'}
                    </span>
                  )}
                </div>
              </div>
            </section>

            <ContentSummary contents={selectedContentList} summaries={contentSummaries} allowMakeup={allowMakeup} />

            <section className="grid gap-5 lg:grid-cols-[1fr_320px]">
              <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-5">
                <p className="text-sm font-semibold text-emerald-700">
                  {allowMakeup ? '应交 / 已提交 / 未提交' : '应交 / 截止提交 / 未提交'}
                </p>
                <p className="mt-3 text-4xl font-bold text-slate-900">
                  {expected} / {submitted} / {summary?.未提交总人数 ?? 0}
                </p>
                <p className="mt-2 text-sm text-slate-600">
                  截止内 {summary?.截止已提交总人数 ?? submitted - late}
                  {allowMakeup ? `，已补交 ${late}` : ''}，后缀无效 {invalid}
                </p>
                <div className="mt-5">
                  <StatusProgressBar segments={segments} />
                </div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <p className="text-sm font-semibold text-slate-600">
                  {allowMakeup ? '当前提交序号接收率' : '当前提交序号截止提交率'}
                </p>
                <div className="mt-4">
                  <StatusDonut rate={rate} segments={segments} />
                </div>
              </div>
            </section>

            <section className="grid gap-4 xl:grid-cols-2">
              {classEntries.map(([className, stat]) => (
                <ClassStatusCard key={className} className={className} stat={stat} allowMakeup={allowMakeup} />
              ))}
              <OtherStatusCard
                submitted={submissionData?.其他已提交名单 || []}
                late={submissionData?.其他已补交名单 || []}
                invalid={submissionData?.其他后缀无效名单 || []}
                allowMakeup={allowMakeup}
              />
            </section>
          </div>
        )}
      </div>
    </main>
  )
}
