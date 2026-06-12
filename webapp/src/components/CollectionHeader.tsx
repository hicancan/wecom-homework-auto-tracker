import { Link } from 'react-router-dom'
import type { CollectionStatus } from '../types'

const HOME_PAGE_URL = 'https://homework.hicancan.top/'
const REPOSITORY_URL = 'https://github.com/hicancan/wecom-homework-auto-tracker'

export function CollectionHeader({
  audience,
  period,
  status,
  title,
  deployTime,
  shareLabel,
  onShare,
}: {
  audience: string
  period: string
  status: CollectionStatus
  title: string
  deployTime: string
  shareLabel: string
  onShare: () => void
}) {
  return (
    <header className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm md:p-7">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap gap-2 text-xs font-semibold">
            <span className="rounded-full bg-sky-100 px-3 py-1 text-sky-800">{audience}</span>
            <span className="rounded-full bg-indigo-100 px-3 py-1 text-indigo-800">{period}</span>
            <span className={`rounded-full px-3 py-1 ${status === 'archived' ? 'bg-slate-200 text-slate-600' : 'bg-emerald-100 text-emerald-700'}`}>
              {status === 'archived' ? '已归档' : '进行中'}
            </span>
          </div>
          <h1 className="mt-4 text-3xl font-bold md:text-5xl">{title}</h1>
          <p className="mt-3 text-sm text-slate-500">网页最后部署时间： {deployTime}</p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
          <button
            type="button"
            onClick={onShare}
            className="inline-flex items-center justify-center rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-800 transition-colors hover:bg-sky-100"
          >
            {shareLabel}
          </button>
          <Link className="inline-flex items-center justify-center rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-100" to="/">
            返回主页
          </Link>
          <a className="inline-flex items-center justify-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-100" href={REPOSITORY_URL} target="_blank" rel="noreferrer">
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
            GitHub
          </a>
        </div>
      </div>
    </header>
  )
}

export function InvalidPanel({ message }: { message: string }) {
  return (
    <section className="mt-6 rounded-lg border border-rose-200 bg-white p-5 text-rose-700 shadow-sm">
      <h2 className="text-lg font-semibold">参数无效</h2>
      <p className="mt-2 text-sm">{message}</p>
      <a className="mt-4 inline-flex text-sm font-semibold text-sky-700" href={HOME_PAGE_URL}>
        返回主页
      </a>
    </section>
  )
}

export function LoadingPanel({ message }: { message: string }) {
  return (
    <section className="mt-6 rounded-lg border border-sky-100 bg-white p-5 text-slate-700 shadow-sm">
      <h2 className="text-lg font-semibold">正在加载</h2>
      <p className="mt-2 text-sm">{message}</p>
    </section>
  )
}
