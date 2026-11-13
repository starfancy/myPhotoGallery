/** 场景/日期筛选的 URL query 与 API 参数转换。 */

/**
 * YYYY-MM-DD → 当天本地 00:00:00 的 epoch 秒（含起始日）。
 * 非法/空值返回 null。
 */
export function dayStartEpoch(dateStr: string): number | null {
  if (!dateStr) return null
  const t = new Date(`${dateStr}T00:00:00`).getTime()
  return Number.isNaN(t) ? null : Math.floor(t / 1000)
}

/**
 * YYYY-MM-DD → 当天本地 23:59:59 的 epoch 秒（含结束日整天）。
 * 非法/空值返回 null。
 */
export function dayEndEpoch(dateStr: string): number | null {
  if (!dateStr) return null
  const t = new Date(`${dateStr}T23:59:59`).getTime()
  return Number.isNaN(t) ? null : Math.floor(t / 1000)
}

/** 把场景+日期筛选写进 URLSearchParams（日期转 epoch 秒）。 */
export function appendFilterParams(
  params: URLSearchParams,
  filter: {
    sceneMajor?: string
    sceneMinor?: string
    dateFrom?: string
    dateTo?: string
  },
): URLSearchParams {
  if (filter.sceneMajor) params.set("scene_major", filter.sceneMajor)
  if (filter.sceneMinor) params.set("scene_minor", filter.sceneMinor)
  const from = dayStartEpoch(filter.dateFrom ?? "")
  const to = dayEndEpoch(filter.dateTo ?? "")
  if (from !== null) params.set("date_from", String(from))
  if (to !== null) params.set("date_to", String(to))
  return params
}
