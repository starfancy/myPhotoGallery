/** 本地时区的「YYYY-MM-DD HH:mm」格式化（入参为 Unix 秒）。 */
export function formatDateTime(unixSec: number): string {
  const d = new Date(unixSec * 1000)
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}`
}
