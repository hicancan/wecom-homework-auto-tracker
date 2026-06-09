import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { loadCollectionRoot } from '../api'
import type { CollectionManifest, CollectionRoot } from '../types'

const HOME_PAGE_URL = 'https://homework.hicancan.top/'

export function HomePage() {
  const [indexData, setIndexData] = useState<CollectionRoot | null>(null)
  const [manifestData, setManifestData] = useState<CollectionManifest | null>(null)
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
    loadCollectionRoot(publicBase)
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
      if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
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
  const collections = useMemo(() => indexData?.收集表列表 || [], [indexData])
  const groupedCollections = useMemo(() => {
    const groups = new Map<string, typeof collections>()
    for (const collection of collections) {
      const groupName = collection.周期?.trim() || '未分组'
      const current = groups.get(groupName) || []
      current.push(collection)
      groups.set(groupName, current)
    }
    return Array.from(groups.entries()).map(([period, items]) => ({
      period,
      items: [...items].sort((a, b) => {
        if (a.状态 !== b.状态) return a.状态 === 'active' ? -1 : 1
        return a.主题.localeCompare(b.主题, 'zh-Hans-CN')
      }),
    }))
  }, [collections])

  return (
    <main className="min-h-screen bg-slate-100 text-slate-900">
      <div className="mx-auto flex min-h-screen max-w-[1400px] flex-col px-4 py-10 md:px-8">
        <header className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm md:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="text-2xl font-bold md:text-4xl">收集表追踪看板</h1>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap sm:justify-end">
              <button
                type="button"
                onClick={handleShareHomeLink}
                className="inline-flex w-full items-center justify-center rounded-md border border-teal-200 bg-teal-50 px-3 py-2 text-sm font-medium text-teal-800 transition hover:bg-teal-100 sm:w-auto"
              >
                分享主页链接
              </button>
              <a
                href="https://github.com/hicancan/wecom-homework-auto-tracker"
                target="_blank"
                rel="noreferrer"
                className="inline-flex w-full items-center justify-center rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 sm:w-auto"
              >
                GitHub
              </a>
            </div>
          </div>
          <p className="mt-3 text-sm text-slate-600">网页最后部署时间： {deployTime}</p>
          {shareFeedback && <p className="mt-2 text-sm text-teal-700">{shareFeedback}</p>}
          {error && <p className="mt-2 text-sm text-rose-700">加载失败：{error}</p>}
        </header>

        <div className="mt-8 space-y-6">
          {groupedCollections.map((group) => {
            const activeCount = group.items.filter((item) => item.状态 === 'active').length
            const archivedCount = group.items.filter((item) => item.状态 === 'archived').length
            return (
              <section key={group.period} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-lg font-bold">{group.period}</h2>
                  <p className="text-sm text-slate-500">进行中 {activeCount} / 归档 {archivedCount}</p>
                </div>
                <div className="mt-4 grid gap-4 md:grid-cols-2">
                  {group.items.map((item) => (
                    <article
                      key={item.收集表ID}
                      className={`rounded-lg border p-4 transition hover:border-sky-300 hover:shadow-sm ${
                        item.状态 === 'archived' ? 'border-slate-200 bg-slate-50 text-slate-500' : 'border-sky-100 bg-white'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-slate-500">{item.对象}</p>
                          <h3 className="mt-2 text-xl font-bold text-slate-900">{item.主题}</h3>
                        </div>
                        <span
                          className={`shrink-0 rounded-full px-2 py-1 text-xs font-semibold ${
                            item.状态 === 'archived' ? 'bg-slate-200 text-slate-600' : 'bg-emerald-100 text-emerald-700'
                          }`}
                        >
                          {item.状态 === 'archived' ? '已归档' : '进行中'}
                        </span>
                      </div>
                      <Link
                        className="mt-4 inline-flex text-sm font-semibold text-sky-700 hover:text-sky-900"
                        to={`/collection/${encodeURIComponent(item.收集表ID)}`}
                      >
                        打开看板
                      </Link>
                    </article>
                  ))}
                </div>
              </section>
            )
          })}
        </div>
      </div>
    </main>
  )
}
