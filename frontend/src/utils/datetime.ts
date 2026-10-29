/** 本地时区的「YYYY-MM-DD HH:mm」格式化（入参为 Unix 秒）。 */
export function formatDateTime(unixSec: number): string {
  const d = new Date(unixSec * 1000)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 与后端 trash.NEVER_PURGE_TS 一致：retention_days=0（永不自动清理）的哨兵。 */
export const NEVER_PURGE_TS = 9_999_999_999

/** 回收站到期时间：哨兵显示「永不」，其余走普通日期时间格式。 */
export function formatPurgeAfter(unixSec: number): string {
  return unixSec >= NEVER_PURGE_TS ? "永不" : formatDateTime(unixSec)
}
