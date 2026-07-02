import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { loadCollectionIndex, loadCollectionRoot, loadSubmissionStat } from '../api'
import { ClassStatusCard, OtherStatusCard } from '../components/ClassStatusCard'
import { CollectionControls } from '../components/CollectionControls'
import { CollectionHeader, InvalidPanel, LoadingPanel } from '../components/CollectionHeader'
import { ContentSummary } from '../components/ContentSummary'
import { SubmissionOverview } from '../components/SubmissionOverview'
import { summarizeContentStats } from '../contentModel'
import { buildStatusSegments } from '../statusModel'
import type { CollectionIndex, CollectionItem, CollectionManifest, CollectionRoot, SubmissionStat } from '../types'

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
  const loadingMessage = useMemo(() => {
    if (invalidMessage) return ''
    if (!rootData) return '正在加载收集表...'
    if (selectedCollection && !collectionIndex) return '正在加载收集表索引...'
    if (collectionIndex && !selectedRef) return '正在切换提交序号...'
    if (selectedRef && !submissionData) return '正在加载提交统计...'
    return ''
  }, [collectionIndex, invalidMessage, rootData, selectedCollection, selectedRef, submissionData])

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
  const unmet = summary?.未提交总人数 ?? 0
  const cutoffSubmitted = summary?.截止已提交总人数 ?? submitted - late
  const status = selectedCollection?.状态 || collectionIndex?.状态 || submissionData?.状态 || 'active'
  const headerAudience = selectedCollection?.对象 || collectionIndex?.对象 || '-'
  const headerPeriod = selectedCollection?.周期 || collectionIndex?.周期 || '未分组'
  const headerTitle = selectedCollection?.主题 || collectionIndex?.主题 || '收集表'
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
        <CollectionHeader
          audience={headerAudience}
          period={headerPeriod}
          status={status}
          title={headerTitle}
          deployTime={deployTime}
          shareLabel={shareLabel}
          onShare={handleShareLink}
        />

        {invalidMessage ? (
          <InvalidPanel message={invalidMessage} />
        ) : loadingMessage ? (
          <LoadingPanel message={loadingMessage} />
        ) : (
          <div className="mt-6 space-y-5">
            <CollectionControls
              collections={collections}
              collectionId={collectionId}
              selectedSeq={selectedSeq}
              collectionIndex={collectionIndex}
              submissionData={submissionData}
              allowMakeup={allowMakeup}
              onCollectionChange={handleCollectionChange}
              onSeqChange={handleSeqChange}
            />

            <ContentSummary contents={selectedContentList} summaries={contentSummaries} allowMakeup={allowMakeup} />

            <SubmissionOverview
              allowMakeup={allowMakeup}
              expected={expected}
              submitted={submitted}
              unmet={unmet}
              cutoffSubmitted={cutoffSubmitted}
              late={late}
              invalid={invalid}
              rate={rate}
              segments={segments}
            />

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
