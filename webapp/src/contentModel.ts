import type { ContentStatPayload, ContentStatSummary, SubmissionStat } from './types'

export function summarizeContentStats(value: SubmissionStat['提交内容统计']): ContentStatSummary[] {
  if (!value) return []
  if (Array.isArray(value)) return value

  return Object.entries(value).map(([content, payload]: [string, ContentStatPayload]) => {
    const totals = Object.values(payload.班级统计 || {}).reduce(
      (acc, stat) => {
        acc.expected += stat.应交人数 || 0
        acc.submitted += stat.已提交人数 || 0
        acc.unmet += stat.未提交人数 || 0
        acc.invalid += stat.后缀无效人数 || 0
        acc.late += stat.已补交人数 || 0
        return acc
      },
      { expected: 0, submitted: 0, unmet: 0, invalid: 0, late: 0 },
    )
    return {
      提交内容: content,
      应交人数: totals.expected,
      已提交人数: totals.submitted,
      未提交人数: totals.unmet,
      后缀无效人数: totals.invalid,
      已补交人数: totals.late,
      提交率: totals.expected ? totals.submitted / totals.expected : 0,
    }
  })
}
