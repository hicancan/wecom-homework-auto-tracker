import { StatusDonut, StatusProgressBar } from './StatusChart'
import type { StatusSegments } from '../statusModel'

export function SubmissionOverview({
  allowMakeup,
  expected,
  submitted,
  unmet,
  cutoffSubmitted,
  late,
  invalid,
  rate,
  segments,
}: {
  allowMakeup: boolean
  expected: number
  submitted: number
  unmet: number
  cutoffSubmitted: number
  late: number
  invalid: number
  rate: number
  segments: StatusSegments
}) {
  return (
    <section className="grid gap-5 lg:grid-cols-[1fr_320px]">
      <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-5">
        <p className="text-sm font-semibold text-emerald-700">
          {allowMakeup ? '应交 / 已提交 / 未提交' : '应交 / 截止提交 / 未提交'}
        </p>
        <p className="mt-3 text-4xl font-bold text-slate-900">
          {expected} / {submitted} / {unmet}
        </p>
        <p className="mt-2 text-sm text-slate-600">
          截止内 {cutoffSubmitted}
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
  )
}
