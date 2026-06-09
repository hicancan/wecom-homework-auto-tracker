import type { ContentStatSummary } from '../types'

export function ContentSummary({
  contents,
  summaries,
}: {
  contents: string[]
  summaries: ContentStatSummary[]
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-700">提交内容</h2>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {contents.map((content) => {
          const summary = summaries.find((item) => item.提交内容 === content)
          return (
            <div key={content} className="rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="text-base font-semibold text-slate-900">{content}</div>
              {summary && (
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full bg-emerald-100 px-2 py-1 text-emerald-800">
                    已交 {summary.已交人数} / 应交 {summary.应交人数}
                  </span>
                  {!!summary.已补交人数 && (
                    <span className="rounded-full bg-sky-100 px-2 py-1 text-sky-800">补交 {summary.已补交人数}</span>
                  )}
                  {!!summary.后缀格式无效人数 && (
                    <span className="rounded-full bg-amber-100 px-2 py-1 text-amber-800">
                      后缀格式无效 {summary.后缀格式无效人数}
                    </span>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
