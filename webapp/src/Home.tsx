import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

type CourseItem = {
  课程: string
  数据文件: string
}

type CourseIndex = {
  更新时间?: string
  最后部署时间?: string
  课程列表: CourseItem[]
}

function Home() {
  const [indexData, setIndexData] = useState<CourseIndex | null>(null)
  const [error, setError] = useState('')
  const publicBase = import.meta.env.BASE_URL || '/'

  useEffect(() => {
    fetch(`${publicBase}courses.json`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`)
        }
        return res.json() as Promise<CourseIndex>
      })
      .then((json) => {
        setIndexData(json)
        setError('')
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : '加载失败')
      })
  }, [publicBase])

  const deployTime = indexData?.最后部署时间 || indexData?.更新时间 || '加载中...'
  const courses = indexData?.课程列表 || []

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_10%,#dbeafe_0%,#f8fafc_45%,#ecfeff_100%)] text-slate-900">
      <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-4 py-12 md:px-8">
        <header className="rounded-3xl border border-sky-100 bg-white/90 p-6 shadow-[0_30px_80px_rgba(14,116,144,0.12)] backdrop-blur md:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="text-2xl font-bold md:text-4xl">课程作业追踪看板</h1>
            <a
              href="https://github.com/hicancan/wecom-homework-auto-tracker"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100"
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
          <p className="mt-3 text-sm text-slate-600">网页最后部署时间：{deployTime}</p>
          <p className="mt-2 text-sm text-slate-600">请选择课程进入看板，路由将保持可分享的课程链接。</p>
        </header>

        {error && (
          <section className="mt-6 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
            数据加载失败：{error}
          </section>
        )}

        <section className="mt-6 grid gap-4 md:grid-cols-2">
          {courses.map((item) => (
            <Link
              key={item.课程}
              to={`/course/${encodeURIComponent(item.课程)}`}
              className="group rounded-2xl border border-sky-100 bg-white/95 p-5 shadow-[0_20px_45px_rgba(14,165,233,0.1)] transition hover:-translate-y-0.5 hover:shadow-[0_25px_50px_rgba(14,165,233,0.16)]"
            >
              <p className="text-xs uppercase tracking-[0.24em] text-sky-700">Course</p>
              <h2 className="mt-2 text-lg font-semibold text-slate-900">{item.课程}</h2>
              <p className="mt-3 text-sm text-slate-500">进入该课程的作业提交看板</p>
              <p className="mt-4 text-sm font-medium text-sky-700 group-hover:text-sky-800">打开看板</p>
            </Link>
          ))}
        </section>
      </div>
    </main>
  )
}

export default Home
