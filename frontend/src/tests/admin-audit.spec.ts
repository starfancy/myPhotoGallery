import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminAudit from "../views/AdminAudit.vue"
import { useToastStore } from "../stores/toast"

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

const now = Math.floor(Date.now() / 1000)
const ENTRIES = [
  { id: 3, ts: now, actor_user_id: 1, actor_ip: "127.0.0.1", action: "image_delete", target: "image:9", detail: "x" },
  { id: 2, ts: now - 60, actor_user_id: null, actor_ip: "10.0.0.5", action: "login_fail", target: null, detail: null },
  { id: 1, ts: now - 120, actor_user_id: null, actor_ip: "127.0.0.1", action: "scan_start", target: "root:1", detail: null },
]

async function mountPage(auditBody: unknown = { entries: ENTRIES, next_cursor: "t_1" }, users = [
  { id: 1, username: "alice" },
]) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as Request).url
    if (url.startsWith("/api/admin/users")) return response(users)
    if (url.startsWith("/api/admin/audit")) return response(auditBody)
    return response({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/audit", component: AdminAudit }],
  })
  await router.push("/admin/audit")
  const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { w, fetchFn }
}

beforeEach(() => { setActivePinia(createPinia()); vi.unstubAllGlobals() })
afterEach(() => {
  // jsdom 无 createObjectURL（测试中直接赋值）；click 走 spy，统一还原
  delete (URL as Partial<typeof URL>).createObjectURL
  delete (URL as Partial<typeof URL>).revokeObjectURL
  vi.restoreAllMocks()
})

// 导出测试专用挂载：组件与断言共享同一个 pinia（toast 断言需要）
async function mountForExport(auditHandler: (u: URL) => unknown) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const raw = typeof input === "string" ? input : (input as Request).url
    if (raw.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
    if (raw.startsWith("/api/admin/audit")) return response(auditHandler(new URL(raw, "http://x")))
    return response({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/audit", component: AdminAudit }],
  })
  await router.push("/admin/audit")
  const w = mount(AdminAudit, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { w, fetchFn, pinia }
}

const exportRow = (id: number) => ({
  id, ts: now, actor_user_id: 1, actor_ip: "127.0.0.1",
  action: "image_delete", target: `image:${id}`, detail: null,
})

function stubDownload() {
  const createObjectURL = vi.fn((_blob: Blob) => "blob:mock")
  const revokeObjectURL = vi.fn()
  URL.createObjectURL = createObjectURL
  URL.revokeObjectURL = revokeObjectURL
  // 在 anchor.click 桩里捕获 download 属性（组件 click 后立即 remove，拿不到节点）
  const downloads: string[] = []
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push(this.download)
  })
  return { createObjectURL, revokeObjectURL, downloads }
}

describe("AdminAudit", () => {
  it("renders rows with labels, mapped username, 匿名 for login_fail and 系统 for scans", async () => {
    const { w } = await mountPage()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).toContain("alice")
    expect(w.text()).toContain("匿名")
    expect(w.text()).toContain("系统")
    expect(w.text()).toContain("10.0.0.5")
    expect(w.text()).toContain("image:9")
  })

  it("falls back to #id（已删除） when user missing", async () => {
    const { w } = await mountPage(undefined, [])
    expect(w.text()).toContain("#1（已删除）")
  })

  it("still lists entries and falls back to #id when users fetch fails", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users"))
        return response({ error: { code: "internal_error", message: "x" } }, 500)
      return response({ entries: ENTRIES, next_cursor: null })
    })
    vi.stubGlobal("fetch", fetchFn)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/admin/audit", component: AdminAudit }],
    })
    await router.push("/admin/audit")
    const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).toContain("#1")
    expect(w.text()).not.toContain("加载失败")
  })

  it("loads more with cursor and merges rows", async () => {
    const { w, fetchFn } = await mountPage()
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1"))
        return response({ entries: [{ id: 4, ts: now - 200, actor_user_id: 1, actor_ip: "127.0.0.1", action: "login_success", target: null, detail: null }], next_cursor: null })
      return response({ entries: [], next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("加载更多"))!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("登录成功")
  })

  it("filters by action and date range and resets to first page", async () => {
    const { w, fetchFn } = await mountPage()
    const select = w.find("select")
    await select.setValue("image_delete")
    await w.find("#audit-from").setValue("2026-10-01")
    await w.find("#audit-to").setValue("2026-10-31")
    await flushPromises()
    const calls = fetchFn.mock.calls as Array<[string]>
    const q = calls.filter((c) => c[0].startsWith("/api/admin/audit")).map((c) => c[0]).pop()!
    expect(q).toContain("action=image_delete")
    const params = new URL(q, "http://x").searchParams
    // 过滤变化重置回第一页：不带游标
    expect(params.get("cursor")).toBeNull()
    // 2026-10-01 00:00 本地（东八区 = 1790630400）；止 = 当天 23:59:59
    expect(Number(params.get("from"))).toBe(
      Math.floor(new Date(2026, 9, 1, 0, 0, 0).getTime() / 1000),
    )
    expect(Number(params.get("to"))).toBe(
      Math.floor(new Date(2026, 9, 31, 23, 59, 59).getTime() / 1000),
    )
  })

  it("shows empty state and error state", async () => {
    const { w } = await mountPage({ entries: [], next_cursor: null })
    expect(w.text()).toContain("暂无审计记录")
  })

  it("shows replacing Chinese error bar on first-page failure and retry reloads", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      return response({ error: { code: "internal_error", message: "Internal Server Error boom" } }, 500)
    })
    vi.stubGlobal("fetch", fetchFn)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/admin/audit", component: AdminAudit }],
    })
    await router.push("/admin/audit")
    const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    // 中文映射文案，不回显后端英文原文；错误条替换表格区
    expect(w.text()).toContain("服务器内部错误")
    expect(w.text()).not.toContain("Internal Server Error boom")
    expect(w.findAll("table")).toHaveLength(0)
    // 重试成功
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      return response({ entries: ENTRIES, next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("重试"))!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).not.toContain("服务器内部错误")
  })

  it("keeps loaded rows on paging failure, shows inline error, and pager retry merges next page", async () => {
    const { w, fetchFn } = await mountPage()
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1"))
        return response({ error: { code: "internal_error", message: "Raw backend English" } }, 500)
      return response({ entries: [], next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("加载更多"))!.trigger("click")
    await flushPromises()
    // 首页行仍在同一张表中；分页错误条为中文、带独立重试
    expect(w.findAll("tbody tr")).toHaveLength(3)
    expect(w.text()).toContain("image:9")
    expect(w.text()).toContain("服务器内部错误")
    expect(w.text()).not.toContain("Raw backend English")
    // 游标未因失败推进：重试仍带同一 cursor，且重试成功后第二页并入同一张表
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1"))
        return response({
          entries: [{ id: 4, ts: now - 200, actor_user_id: 1, actor_ip: "127.0.0.1", action: "login_success", target: null, detail: null }],
          next_cursor: null,
        })
      return response({ entries: [], next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("重试"))!.trigger("click")
    await flushPromises()
    expect(w.findAll("tbody tr")).toHaveLength(4)
    expect(w.text()).toContain("登录成功")
    expect(w.text()).toContain("image:9")
    expect(w.text()).not.toContain("服务器内部错误")
  })

  it("resets pager when filter changes while loadMore is in flight; stale page is not appended", async () => {
    let resolvePage2!: (r: Response) => void
    const pendingPage2 = new Promise<Response>((res) => { resolvePage2 = res })
    const { w, fetchFn } = await mountPage()
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1")) return pendingPage2
      // 过滤重置请求（无 cursor）立即返回
      return response({ entries: [ENTRIES[0]], next_cursor: "t_2" })
    })
    const moreBtn = () => w.findAll("button").find((b) => /加载(更多|中)/.test(b.text()))!
    await moreBtn().trigger("click")
    await flushPromises()
    expect(moreBtn().attributes("disabled")).toBeDefined()
    expect(moreBtn().text()).toBe("加载中...")
    // 过滤变化触发 reload，使在途 loadMore 失效
    await w.find("select").setValue("image_delete")
    await flushPromises()
    const resetUrls = (fetchFn.mock.calls as Array<[string]>)
      .map((c) => c[0])
      .filter((u) => u.startsWith("/api/admin/audit") && u.includes("action=image_delete"))
    expect(resetUrls.length).toBeGreaterThan(0)
    for (const u of resetUrls) expect(new URL(u, "http://x").searchParams.get("cursor")).toBeNull()
    // 旧 loadMore 此刻才返回
    resolvePage2(response({
      entries: [{ id: 999, ts: now - 300, actor_user_id: 1, actor_ip: "127.0.0.1", action: "login_success", target: "STALE", detail: null }],
      next_cursor: null,
    }))
    await flushPromises()
    expect(moreBtn().attributes("disabled")).toBeUndefined()
    expect(moreBtn().text()).toBe("加载更多")
    // 注意「登录成功」也存在于过滤下拉项中，故只在 tbody 内断言旧页未被追加
    expect(w.find("tbody").text()).not.toContain("登录成功")
    expect(w.find("tbody").text()).not.toContain("STALE")
    expect(w.find("tbody").text()).toContain("image:9")
  })

  it("hides pager when a filter reload fails after rows loaded; inline retry restores it", async () => {
    const { w, fetchFn } = await mountPage()
    const hasMoreBtn = () => w.findAll("button").some((b) => b.text().includes("加载更多"))
    expect(hasMoreBtn()).toBe(true)
    // 过滤变化触发的 reload 失败：首页数据与 next_cursor=t_1 仍在
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      return response({ error: { code: "internal_error", message: "Raw backend English" } }, 500)
    })
    await w.find("select").setValue("image_delete")
    await flushPromises()
    // 已有行保留；行内 reload 错误条显示中文映射文案；分页器整块隐藏
    expect(w.findAll("tbody tr")).toHaveLength(3)
    expect(w.text()).toContain("image:9")
    expect(w.text()).toContain("服务器内部错误")
    expect(w.text()).not.toContain("Raw backend English")
    expect(hasMoreBtn()).toBe(false)
    // 行内错误条的重试成功：错误消失、分页器恢复
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      return response({ entries: ENTRIES, next_cursor: "t_9" })
    })
    await w.findAll("button").find((b) => b.text().includes("重试"))!.trigger("click")
    await flushPromises()
    expect(w.text()).not.toContain("服务器内部错误")
    expect(hasMoreBtn()).toBe(true)
  })

  it("CSV export pages at limit=500 and triggers one browser download", async () => {
    const { createObjectURL, downloads } = stubDownload()
    let exportPage = 0
    const { w, fetchFn } = await mountForExport((u) => {
      if (u.searchParams.get("limit") === "500") {
        exportPage += 1
        if (exportPage === 1) return { entries: [exportRow(101), exportRow(102)], next_cursor: "exp1" }
        return { entries: [exportRow(103)], next_cursor: null }
      }
      // 首屏浏览页（limit=100）：有数据，导出按钮可用
      return { entries: [ENTRIES[0]], next_cursor: null }
    })
    await w.findAll("button").find((b) => b.text().includes("导出 CSV"))!.trigger("click")
    await flushPromises()

    const exportUrls = (fetchFn.mock.calls as Array<[string]>)
      .map((c) => c[0])
      .filter((u) => u.startsWith("/api/admin/audit") &&
        new URL(u, "http://x").searchParams.get("limit") === "500")
    expect(exportUrls).toHaveLength(2)
    expect(new URL(exportUrls[0], "http://x").searchParams.get("cursor")).toBeNull()
    expect(new URL(exportUrls[1], "http://x").searchParams.get("cursor")).toBe("exp1")
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    // Blob 必须带 UTF-8 CSV MIME；文件名 audit-YYYYMMDD-HHmmss.csv
    const blob = createObjectURL.mock.calls[0][0]
    expect(blob).toBeInstanceOf(Blob)
    expect((blob as Blob).type).toBe("text/csv;charset=utf-8")
    expect(downloads).toHaveLength(1)
    expect(downloads[0]).toMatch(/^audit-\d{8}-\d{6}\.csv$/)
  })

  it("cancel on an in-flight page is operable, silent, and leaves no download", async () => {
    const { createObjectURL } = stubDownload()
    let rejectExport!: (e: unknown) => void
    const pendingExport = new Promise<Response>((_, reject) => { rejectExport = reject })
    const { w, fetchFn, pinia } = await mountForExport(() => ({
      entries: [ENTRIES[0]], next_cursor: null,
    }))
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : (input as Request).url
      if (raw.startsWith("/api/admin/users"))
        return response([{ id: 1, username: "alice" }])
      if (new URL(raw, "http://x").searchParams.get("limit") === "500")
        return pendingExport // 第一页导出挂起
      return response({ entries: [ENTRIES[0]], next_cursor: null })
    })

    const exportBtn = () => w.findAll("button").find((b) => /导出|取消/.test(b.text()))!
    await exportBtn().trigger("click")
    await flushPromises()
    // 导出中：按钮变「取消」、可点、不灰
    expect(exportBtn().text()).toContain("取消")
    expect(exportBtn().attributes("disabled")).toBeUndefined()
    expect(exportBtn().classes()).not.toContain("opacity-40")

    await exportBtn().trigger("click") // 点击取消 → abort()
    // 底层 fetch 随 abort 以 AbortError reject（api.ts 会包成 network_error）
    rejectExport(new DOMException("Aborted", "AbortError"))
    await flushPromises()

    const toast = useToastStore(pinia)
    expect(toast.items).toHaveLength(0) // 取消后无错误 toast
    expect(createObjectURL).not.toHaveBeenCalled() // 无文件
    // 按钮恢复「导出 CSV」、可点、常态
    expect(exportBtn().text()).toContain("导出 CSV")
    expect(exportBtn().attributes("disabled")).toBeUndefined()
    expect(exportBtn().classes()).not.toContain("opacity-40")
  })

  it("snapshots filters at export start: mid-export filter change cannot mix into later pages", async () => {
    const { createObjectURL } = stubDownload()
    let resolvePage2!: (r: Response) => void
    const pendingPage2 = new Promise<Response>((res) => { resolvePage2 = res })
    const { w, fetchFn } = await mountForExport(() => ({
      entries: [ENTRIES[0]], next_cursor: null,
    }))
    // 先在 image_delete 过滤下列表加载一次
    await w.find("select").setValue("image_delete")
    await flushPromises()

    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : (input as Request).url
      if (raw.startsWith("/api/admin/users"))
        return response([{ id: 1, username: "alice" }])
      const u = new URL(raw, "http://x")
      if (u.searchParams.get("limit") === "500" && u.searchParams.get("cursor") === "exp1")
        return pendingPage2 // 第二页导出挂起，等待过滤切换后再放行
      if (u.searchParams.get("limit") === "500" && u.searchParams.get("cursor") === "exp2")
        return response({ entries: [exportRow(103)], next_cursor: null }) // 第三页：过滤切换后才发出
      if (u.searchParams.get("limit") === "500")
        return response({ entries: [exportRow(101)], next_cursor: "exp1" })
      // 过滤切换触发的浏览 reload（limit=100，新 action）
      return response({ entries: [ENTRIES[0]], next_cursor: null })
    })

    await w.findAll("button").find((b) => b.text().includes("导出 CSV"))!.trigger("click")
    await flushPromises() // 第一页已回，第二页在途
    // 导出途中切换过滤：只触发浏览 reload，不得改写导出请求
    await w.find("select").setValue("login_success")
    await flushPromises()
    resolvePage2(response({ entries: [exportRow(102)], next_cursor: "exp2" }))
    await flushPromises() // 第二页回后第三页发出

    const exportUrls = (fetchFn.mock.calls as Array<[string]>)
      .map((c) => c[0])
      .filter((u) => new URL(u, "http://x").searchParams.get("limit") === "500")
    expect(exportUrls).toHaveLength(3)
    const pages = exportUrls.map((u) => new URL(u, "http://x").searchParams)
    // 三页全部使用导出开始时的旧过滤；游标依次 null/exp1/exp2，无 login_success 混入
    for (const p of pages) expect(p.get("action")).toBe("image_delete")
    expect(pages.map((p) => p.get("cursor"))).toEqual([null, "exp1", "exp2"])
    expect(createObjectURL).toHaveBeenCalledTimes(1)
  })

  it("CSV export over 10,000 rows shows limit toast and never downloads", async () => {
    const { createObjectURL } = stubDownload()
    let exportPages = 0
    const { w, pinia } = await mountForExport((u) => {
      if (u.searchParams.get("limit") === "500") {
        exportPages += 1
        return {
          entries: Array.from({ length: 500 }, (_, i) => exportRow((exportPages - 1) * 500 + i)),
          next_cursor: `exp${exportPages}`, // 永远有下一页
        }
      }
      return { entries: [ENTRIES[0]], next_cursor: null }
    })
    await w.findAll("button").find((b) => b.text().includes("导出 CSV"))!.trigger("click")
    await flushPromises()

    // 500 * 20 = 10,000：恰好拉满 20 页后因仍有下一页中止，不落盘半截文件
    expect(exportPages).toBe(20)
    const toast = useToastStore(pinia)
    expect(toast.items.some((t) => t.text.includes("最多导出 10,000 条"))).toBe(true)
    expect(createObjectURL).not.toHaveBeenCalled()
    // 按钮恢复可点（导出态复位）
    expect(w.findAll("button").some((b) => b.text().includes("导出 CSV"))).toBe(true)
  })
})
