import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { type CourseIndex, type CourseManifest, loadCourseIndex } from './courseIndexLoader'

function Home() {
  const HOME_PAGE_URL = 'https://homework.hicancan.top/'
  const [indexData, setIndexData] = useState<CourseIndex | null>(null)
  const [manifestData, setManifestData] = useState<CourseManifest | null>(null)
  const [error, setError] = useState('')
  const [shareFeedback, setShareFeedback] = useState('')
  const publicBase = import.meta.env.BASE_URL || '/'

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
        setError('')
      })
      .catch((e: unknown) => {
        if (!active) return
        setManifestData(null)
        setIndexData(null)
        setError(e instanceof Error ? e.message : '加载失败')
      })
    return () => {
      active = false
    }
  }, [publicBase])

  async function handleShareHomeLink() {
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error('clipboard unavailable')
      }
      await navigator.clipboard.writeText(HOME_PAGE_URL)
      setShareFeedback('主页链接已复制')
    } catch {
      setShareFeedback('复制失败，请手动复制主页链接')
    }
  }

  const deployTime =
    manifestData?.最后部署时间 ||
    indexData?.最后部署时间 ||
    manifestData?.更新时间 ||
    indexData?.更新时间 ||
    '加载中...'
  const courses = useMemo(() => indexData?.课程列表 || [], [indexData])
  const groupedCourses = useMemo(() => {
    const groups = new Map<string, typeof courses>()
    for (const course of courses) {
      const groupName = course.周期?.trim() || '未分组'
      const current = groups.get(groupName) || []
      current.push(course)
      groups.set(groupName, current)
    }
    return Array.from(groups.entries()).map(([period, items]) => ({
      period,
      items: [...items].sort((a, b) => {
        if (a.状态 !== b.状态) return a.状态 === 'active' ? -1 : 1
        return a.主题.localeCompare(b.主题, 'zh-Hans-CN')
      }),
    }))
  }, [courses])

  return (
    <main className="min-h-screen bg-slate-100 text-slate-900">
      <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col px-4 py-12 md:px-8">
        <header className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm md:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="text-2xl font-bold md:text-4xl">课程作业追踪看板</h1>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap sm:justify-end">
              <button
                type="button"
                onClick={handleShareHomeLink}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-teal-200 bg-teal-50 px-3 py-2 text-sm font-medium text-teal-800 transition hover:bg-teal-100 sm:w-auto"
              >
                <svg
                  viewBox="0 0 24 24"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M8.5 12a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z" />
                  <path d="M15.5 19a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z" />
                  <path d="M8 9.5l7 5" />
                </svg>
                分享主页链接
              </button>
              <a
                href="https://github.com/hicancan/wecom-homework-auto-tracker"
                target="_blank"
                rel="noreferrer"
                className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 sm:w-auto"
              >
                <svg
                  viewBox="0 0 24 24"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  <path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.21.68-.48v-1.69c-2.78.61-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.48-1.11-1.48-.91-.62.07-.61.07-.61 1.01.07 1.54 1.04 1.54 1.04.89 1.54 2.34 1.09 2.91.84.09-.65.35-1.09.63-1.34-2.22-.26-4.56-1.12-4.56-4.96 0-1.1.39-2 1.03-2.7-.1-.25-.45-1.29.1-2.67 0 0 .84-.27 2.75 1.03A9.55 9.55 0 0 1 12 6.84c.85 0 1.71.12 2.51.36 1.9-1.3 2.75-1.03 2.75-1.03.55 1.38.2 2.42.1 2.67.64.7 1.03 1.6 1.03 2.7 0 3.85-2.34 4.7-4.57 4.96.36.31.67.91.67 1.84v2.73c0 .27.18.58.69.48A10 10 0 0 0 12 2z" />
                </svg>
                GitHub
              </a>
            </div>
          </div>
          <p className="mt-3 text-sm text-slate-600">网页最后部署时间：{deployTime}</p>
          {shareFeedback && <p className="mt-2 text-xs text-slate-500">{shareFeedback}</p>}
        </header>

        {error && (
          <section className="mt-6 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            数据加载失败：{error}
          </section>
        )}

        <section className="mt-6 space-y-6">
          {groupedCourses.map((group) => (
            <div key={group.period}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-slate-800">{group.period}</h2>
                <span className="text-xs text-slate-500">
                  进行中 {group.items.filter((item) => item.状态 === 'active').length} / 归档{' '}
                  {group.items.filter((item) => item.状态 === 'archived').length}
                </span>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                {group.items.map((item) => {
                  const archived = item.状态 === 'archived'
                  return (
                    <Link
                      key={item.课程}
                      to={`/course/${encodeURIComponent(item.课程)}`}
                      className={`group rounded-lg border bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
                        archived ? 'border-slate-200 opacity-80 hover:opacity-100' : 'border-sky-200'
                      }`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="text-xs font-medium text-slate-500">{item.对象}</p>
                          <h3 className="mt-1 text-lg font-semibold text-slate-900">{item.主题}</h3>
                        </div>
                        <span
                          className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                            archived ? 'bg-slate-100 text-slate-600' : 'bg-emerald-50 text-emerald-700'
                          }`}
                        >
                          {archived ? '已归档' : '进行中'}
                        </span>
                      </div>
                      <p className="mt-4 text-sm font-medium text-sky-700 group-hover:text-sky-800">打开看板</p>
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        </section>
      </div>
    </main>
  )
}

export default Home
