/** P7: 审计日志前端 CSV 导出。纯函数 + 收集器；不碰 DOM，便于测试。 */

export interface AuditCsvRow {
  id: number
  ts: number
  actor_user_id: number | null
  actor_ip: string
  action: string
  target: string | null
  detail: string | null
}

export const AUDIT_EXPORT_LIMIT = 10_000
export const AUDIT_EXPORT_PAGE_SIZE = 500
const BOM = "﻿"
const HEADER = "id,time,actor_user_id,actor_ip,action,target,detail"

export class AuditExportLimitError extends Error {
  constructor(readonly fetched: number) {
    super(`audit export limit reached: ${fetched}`)
  }
}
export class AuditExportAborted extends Error {}

const pad = (n: number) => String(n).padStart(2, "0")

/** 固定格式的本地时区 ISO 时间：YYYY-MM-DDTHH:mm:ss±HH:MM（不用 toLocaleString，防 locale 漂移）。 */
export function toIsoLocal(unixSec: number): string {
  const d = new Date(unixSec * 1000)
  const offMin = -d.getTimezoneOffset()
  const sign = offMin >= 0 ? "+" : "-"
  const ah = Math.floor(Math.abs(offMin) / 60)
  const am = Math.abs(offMin) % 60
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${sign}${pad(ah)}:${pad(am)}`
  )
}

function esc(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** 行 → CSV 文本（含 BOM、表头、CRLF）。action 刻意输出原始英文键。
 *  只有 target/detail 两个自由文本列做 RFC 4180 转义；数字/IP 列不含分隔符。 */
export function auditRowsToCsv(rows: AuditCsvRow[]): string {
  const lines = [HEADER]
  for (const r of rows) {
    lines.push(
      [
        String(r.id),
        toIsoLocal(r.ts),
        r.actor_user_id === null ? "" : String(r.actor_user_id),
        String(r.actor_ip),
        String(r.action),
        esc(r.target),
        esc(r.detail),
      ].join(","),
    )
  }
  return BOM + lines.join("\r\n") + "\r\n"
}

interface Page {
  entries: AuditCsvRow[]
  next_cursor: string | null
}

/**
 * 按过滤条件（封装在 fetchPage 闭包里）循环游标拉取并拼成 CSV 字符串。
 * 达 10,000 仍有下一页 → AuditExportLimitError（调用方不得落盘半截文件）；
 * signal abort → AuditExportAborted。
 */
export async function collectAuditCsv(
  fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<Page>,
  opts: { signal: AbortSignal; onProgress?: (n: number) => void },
): Promise<string> {
  const all: AuditCsvRow[] = []
  let cursor: string | null = null
  do {
    if (opts.signal.aborted) throw new AuditExportAborted()
    let page: Page
    try {
      page = await fetchPage(cursor, opts.signal)
    } catch (err) {
      // abort() 在 await 期间触发时，fetch 以 AbortError reject（经 api.ts 会被
      // 包成 HttpError(0,"network_error")），await 后的 aborted 检查跑不到——
      // 这里按 signal 状态归一为用户取消；真实失败原样上抛。
      if (opts.signal.aborted) throw new AuditExportAborted()
      throw err
    }
    if (opts.signal.aborted) throw new AuditExportAborted()
    all.push(...page.entries)
    opts.onProgress?.(all.length)
    if (all.length > AUDIT_EXPORT_LIMIT ||
        (all.length === AUDIT_EXPORT_LIMIT && page.next_cursor !== null)) {
      throw new AuditExportLimitError(all.length)
    }
    cursor = page.next_cursor
  } while (cursor !== null)
  return auditRowsToCsv(all)
}

/** audit-YYYYMMDD-HHmmss.csv（浏览器本地时间）。 */
export function auditCsvFilename(now: Date = new Date()): string {
  const p = (n: number) => pad(n)
  return `audit-${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}` +
    `-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}.csv`
}
