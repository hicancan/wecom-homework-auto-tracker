import { StatusLegend } from './StatusLegend'
import type { CollectionIndex, CollectionItem, SubmissionStat } from '../types'

export function CollectionControls({
  collections,
  collectionId,
  selectedSeq,
  collectionIndex,
  submissionData,
  allowMakeup,
  onCollectionChange,
  onSeqChange,
}: {
  collections: CollectionItem[]
  collectionId: string
  selectedSeq: string
  collectionIndex: CollectionIndex | null
  submissionData: SubmissionStat | null
  allowMakeup: boolean
  onCollectionChange: (nextId: string) => void
  onSeqChange: (nextSeq: string) => void
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm font-semibold text-slate-700">
          收集表
          <select
            className="mt-2 w-full rounded-md border border-sky-200 bg-white px-3 py-2 text-base text-slate-900 outline-none focus:border-sky-500"
            value={collectionId}
            onChange={(event) => onCollectionChange(event.target.value)}
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
            onChange={(event) => onSeqChange(event.target.value)}
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
              allowMakeup ? 'border-sky-200 bg-sky-50 text-sky-800' : 'border-slate-200 bg-slate-100 text-slate-700'
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
  )
}
