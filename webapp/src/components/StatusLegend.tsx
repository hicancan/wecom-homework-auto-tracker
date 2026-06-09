const items = [
  ['已提交', 'bg-emerald-500'],
  ['后缀格式无效', 'bg-amber-500'],
  ['未交', 'bg-rose-500'],
] as const

const makeupItem = ['补交', 'bg-sky-500'] as const

export function StatusLegend({ allowMakeup }: { allowMakeup: boolean }) {
  const visibleItems = allowMakeup ? [items[0], makeupItem, ...items.slice(1)] : items
  return (
    <div className="flex flex-wrap gap-2 text-xs text-slate-600">
      {visibleItems.map(([label, color]) => (
        <span key={label} className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-1">
          <span className={`h-2 w-2 rounded-full ${color}`} />
          {label}
        </span>
      ))}
    </div>
  )
}
