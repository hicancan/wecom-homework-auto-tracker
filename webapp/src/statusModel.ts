export type StatusSegments = {
  total: number
  submitted: number
  late: number
  invalid: number
  missing: number
}

export function clampRate(rate: number): number {
  if (Number.isNaN(rate)) return 0
  if (rate < 0) return 0
  if (rate > 1) return 1
  return rate
}

export function buildStatusSegments(expected: number, submitted: number, late: number, invalid: number): StatusSegments {
  const safeExpected = Math.max(0, expected)
  const safeLate = Math.max(0, late)
  const safeSubmitted = Math.max(0, submitted)
  const safeInvalid = Math.max(0, invalid)
  const cutoffSubmitted = Math.max(0, safeSubmitted - safeLate)
  const missing = Math.max(0, safeExpected - cutoffSubmitted - safeLate - safeInvalid)
  return {
    total: safeExpected,
    submitted: cutoffSubmitted,
    late: safeLate,
    invalid: safeInvalid,
    missing,
  }
}
