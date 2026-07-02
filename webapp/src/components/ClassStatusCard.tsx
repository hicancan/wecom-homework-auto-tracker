import type { ClassStat } from '../types'
import { buildStatusSegments } from '../statusModel'
import { StatusProgressBar } from './StatusChart'

type Tone = {
  label: string
  className: string
}

type StudentRecord = {
  studentNo: string
  label: string
  className: string
}

const tones = {
  submitted: { label: '已提交', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  late: { label: '已补交', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  invalid: { label: '后缀无效', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  unmet: { label: '未提交', className: 'border-rose-200 bg-rose-50 text-rose-800' },
} satisfies Record<string, Tone>

function addRecords(records: StudentRecord[], values: string[] | undefined, tone: Tone, seen: Set<string>) {
  for (const value of values || []) {
    const studentNo = String(value).trim()
    if (!studentNo || seen.has(studentNo)) continue
    seen.add(studentNo)
    records.push({ studentNo, label: tone.label, className: tone.className })
  }
}

function buildClassRecords(stat: ClassStat, allowMakeup: boolean): StudentRecord[] {
  const records: StudentRecord[] = []
  const seen = new Set<string>()
  addRecords(records, stat.截止已提交名单 || stat.已提交名单, tones.submitted, seen)
  if (allowMakeup) addRecords(records, stat.已补交名单, tones.late, seen)
  addRecords(records, stat.后缀无效名单, tones.invalid, seen)
  addRecords(records, stat.未提交名单, tones.unmet, seen)
  return records.sort((a, b) => a.studentNo.localeCompare(b.studentNo))
}

export function ClassStatusCard({ className, stat, allowMakeup }: { className: string; stat: ClassStat; allowMakeup: boolean }) {
  const records = buildClassRecords(stat, allowMakeup)
  const segments = buildStatusSegments(
    stat.应交人数,
    stat.已提交人数,
    allowMakeup ? stat.已补交人数 || 0 : 0,
    stat.后缀无效人数 || 0,
  )

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold text-slate-900">{className}</h3>
          <p className="mt-1 text-sm text-slate-500">
            应交 {stat.应交人数} / {allowMakeup ? '已提交' : '截止提交'} {stat.已提交人数} / 未提交 {stat.未提交人数}
          </p>
        </div>
        <div className="text-right text-sm font-semibold text-slate-700">{(stat.提交率 * 100).toFixed(2)}%</div>
      </div>
      <div className="mt-4">
        <StatusProgressBar segments={segments} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {records.length ? (
          records.map((record) => (
            <span key={`${record.studentNo}-${record.label}`} className={`rounded-full border px-2 py-1 text-xs ${record.className}`}>
              {record.studentNo} {record.label}
            </span>
          ))
        ) : (
          <span className="text-sm text-slate-500">暂无名单</span>
        )}
      </div>
    </section>
  )
}

export function OtherStatusCard({
  submitted,
  late,
  invalid,
  allowMakeup,
}: {
  submitted: string[]
  late: string[]
  invalid: string[]
  allowMakeup: boolean
}) {
  const records: StudentRecord[] = []
  const seen = new Set<string>()
  addRecords(records, submitted, tones.submitted, seen)
  if (allowMakeup) addRecords(records, late, tones.late, seen)
  addRecords(records, invalid, tones.invalid, seen)
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="text-lg font-bold text-slate-900">其他</h3>
      <div className="mt-4 flex flex-wrap gap-2">
        {records.length ? (
          records.map((record) => (
            <span key={`${record.studentNo}-${record.label}`} className={`rounded-full border px-2 py-1 text-xs ${record.className}`}>
              {record.studentNo} {record.label}
            </span>
          ))
        ) : (
          <span className="text-sm text-slate-500">暂无其他同学提交记录</span>
        )}
      </div>
    </section>
  )
}
