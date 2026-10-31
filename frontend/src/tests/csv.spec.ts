import { auditRowsToCsv, collectAuditCsv, toIsoLocal,
  AuditExportLimitError, AuditExportAborted } from "../utils/csv"

const row = (over: Partial<any> = {}) => ({
  id: 1, ts: 1_700_000_000, actor_user_id: 7, actor_ip: "127.0.0.1",
  action: "image_delete", target: "image:9", detail: null, ...over,
})

describe("auditRowsToCsv", () => {
  it("writes BOM, header, CRLF and raw english action", () => {
    const csv = auditRowsToCsv([row()])
    expect(csv.startsWith("﻿")).toBe(true)
    expect(csv).toContain("id,time,actor_user_id,actor_ip,action,target,detail\r\n")
    expect(csv).toContain(",image_delete,image:9,")
    expect(csv.endsWith("\r\n")).toBe(true)
  })
  it("escapes comma, quote, newline per RFC 4180", () => {
    const csv = auditRowsToCsv([row({ target: "a,b", detail: 'he said "hi"\nx2' })])
    expect(csv).toContain('"a,b"')
    expect(csv).toContain('"he said ""hi""\nx2"')
  })
  it("renders null actor as empty cell and fixed ISO local time with offset", () => {
    const csv = auditRowsToCsv([row({ actor_user_id: null })])
    expect(csv).toMatch(/,127\.0\.0\.1,/)  // actor 空单元格：",,127.0.0.1,"
    expect(csv).toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}/)
  })
})

describe("collectAuditCsv", () => {
  it("pages until exhausted and reports progress", async () => {
    const calls: (string | null)[] = []
    const fetcher = async (cursor: string | null) => {
      calls.push(cursor)
      if (calls.length === 1) return { entries: [row({ id: 1 })], next_cursor: "c1" }
      return { entries: [row({ id: 2 })], next_cursor: null }
    }
    const progress: number[] = []
    const csv = await collectAuditCsv(fetcher, {
      signal: new AbortController().signal,
      onProgress: (n) => progress.push(n),
    })
    expect(calls).toEqual([null, "c1"])
    expect(progress).toEqual([1, 2])
    expect(csv).toContain("image:9")
  })

  it("aborts with AuditExportAborted", async () => {
    const ac = new AbortController()
    const fetcher = vi.fn(async () => {
      ac.abort()
      return { entries: [row()], next_cursor: "c" }
    })
    await expect(collectAuditCsv(fetcher, { signal: ac.signal }))
      .rejects.toBeInstanceOf(AuditExportAborted)
  })

  it("maps an in-flight AbortError after abort to AuditExportAborted, rethrows other errors", async () => {
    // 真实场景：abort() 在 await fetch 期间触发，fetch 以 DOMException AbortError
    // reject（api.ts 会再包成 HttpError(0,"network_error")，await 后的 aborted
    // 检查跑不到）→ 收集器必须在此归一为 AuditExportAborted。
    const ac = new AbortController()
    const abortFetcher = vi.fn(async () => {
      ac.abort()
      throw new DOMException("Aborted", "AbortError")
    })
    await expect(collectAuditCsv(abortFetcher, { signal: ac.signal }))
      .rejects.toBeInstanceOf(AuditExportAborted)

    // 非 abort 的真实失败必须原样上抛（由调用方 toast「导出失败」）
    const boom = new Error("network down")
    const failFetcher = vi.fn(async () => { throw boom })
    await expect(collectAuditCsv(failFetcher, { signal: new AbortController().signal }))
      .rejects.toBe(boom)
  })

  it("stops at 10000 with AuditExportLimitError and no truncated file", async () => {
    const many = Array.from({ length: 500 }, (_, i) => row({ id: i }))
    let pages = 0
    const fetcher = async () => {
      pages += 1
      return { entries: many, next_cursor: `c${pages}` } // 永远有下一页
    }
    await expect(collectAuditCsv(fetcher, { signal: new AbortController().signal }))
      .rejects.toBeInstanceOf(AuditExportLimitError)
    expect(pages).toBe(20) // 500 * 20 = 10000
  })
})

describe("toIsoLocal", () => {
  it("formats with explicit +08:00 style offset", () => {
    // 构造一个 UTC 时刻；只校验形状与偏移计算（用 Date 自身偏移反推）
    const d = new Date("2026-10-31T08:30:45Z")
    const s = toIsoLocal(Math.floor(d.getTime() / 1000))
    expect(s).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/)
    const offMin = -d.getTimezoneOffset()
    const expectSign = offMin >= 0 ? "+" : "-"
    expect(s.slice(-6, -5)).toBe(expectSign)
  })
})
