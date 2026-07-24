import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { createMemoryHistory, createRouter } from "vue-router"
import AdminOverview from "../views/AdminOverview.vue"

// Router is required because AdminOverview renders <router-link to="/galleries">
// and AppHeader's useRouter() would otherwise fail to inject.
function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/galleries", component: { template: "<div />" } },
      { path: "/admin", component: { template: "<div />" } },
      { path: "/admin/galleries", component: { template: "<div />" } },
    ],
  })
}

function mountView() {
  return mount(AdminOverview, {
    global: { plugins: [createPinia(), makeRouter()] },
  })
}

function mockStatus(payload: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status,
        headers: { "content-type": "application/json" },
      }),
    ),
  )
}

const FULL_PAYLOAD = {
  stats: { images: 1234, galleries: 3, roots: 5, users: 2 },
  scan_statuses: [
    {
      root_id: 1,
      gallery_id: 1,
      label: "Main",
      absolute_path: "/photos",
      enabled: true,
      status: "idle",
      last_scan_at: 1_700_000_000,
      last_scan_status: "ok",
      last_scan_error: null,
    },
    {
      root_id: 2,
      gallery_id: 1,
      label: "Broken",
      absolute_path: "/gone",
      enabled: true,
      status: "idle",
      last_scan_at: null,
      last_scan_status: "error",
      last_scan_error: "path unreadable",
    },
  ],
  recent_audit: [
    {
      id: 10,
      ts: 1_700_000_100,
      actor_user_id: 1,
      actor_ip: "127.0.0.1",
      action: "gallery_create",
      target: "gallery:1",
      detail: "name=Home",
    },
    {
      id: 9,
      ts: 1_700_000_050,
      actor_user_id: null,
      actor_ip: "127.0.0.1",
      action: "scan_start",
      target: "root:1",
      detail: null,
    },
  ],
}

describe("AdminOverview", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("shows loading state before fetch resolves", () => {
    // Never-resolving fetch keeps the view in the loading state.
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
    const w = mountView()
    expect(w.text()).toContain("加载中")
  })

  it("renders stats, scan statuses, and recent audit on success", async () => {
    mockStatus(FULL_PAYLOAD)
    const w = mountView()
    await flushPromises()

    // Stats: assert the number renders in any common locale form
    // (en-US: "1,234", zh-CN: "1,234", de: "1.234", CI-safe fallback: "1234").
    const t = w.text()
    expect(t).toMatch(/1[,. ]?234/)
    expect(t).toContain("图片")
    expect(t).toContain("图库")
    expect(t).toContain("根目录")
    expect(t).toContain("用户")

    // Scan status list: labels + status text (Chinese) present.
    expect(w.text()).toContain("Main")
    expect(w.text()).toContain("/photos")
    expect(w.text()).toContain("空闲") // status=idle
    expect(w.text()).toContain("path unreadable") // error message shown

    // Recent audit: Chinese action labels rendered.
    expect(w.text()).toContain("创建图库")
    expect(w.text()).toContain("扫描开始")
    expect(w.text()).toContain("gallery:1")
    expect(w.text()).toContain("name=Home")
  })

  it("renders empty-state messages when there are no roots or audits", async () => {
    mockStatus({
      stats: { images: 0, galleries: 0, roots: 0, users: 1 },
      scan_statuses: [],
      recent_audit: [],
    })
    const w = mountView()
    await flushPromises()
    expect(w.text()).toContain("暂无根目录")
    expect(w.text()).toContain("暂无审计记录")
  })

  it("shows an error message when the API returns 4xx", async () => {
    mockStatus({ error: { code: "forbidden", message: "admin only" } }, 403)
    const w = mountView()
    await flushPromises()
    expect(w.text()).toContain("admin only")
  })

  it("shows an unknown action code verbatim when not in the label map", async () => {
    // Guards against silent fallback when the backend adds a new action.
    mockStatus({
      stats: { images: 0, galleries: 0, roots: 0, users: 1 },
      scan_statuses: [],
      recent_audit: [
        {
          id: 1,
          ts: 1_700_000_000,
          actor_user_id: null,
          actor_ip: "cli",
          action: "some_future_action",
          target: null,
          detail: null,
        },
      ],
    })
    const w = mountView()
    await flushPromises()
    expect(w.text()).toContain("some_future_action")
  })

  it("renders the manage-galleries link pointing to /admin/galleries", async () => {
    mockStatus(FULL_PAYLOAD)
    const w = mountView()
    await flushPromises()
    // AppHeader also renders a router-link to /galleries (the brand); pick
    // the one whose text is "管理图库" specifically.
    const links = w.findAll('a[href="/admin/galleries"]')
    const manage = links.find((a) => a.text().includes("管理图库"))
    expect(manage).toBeDefined()
  })

  it("colors the scan status by state (idle/queued/running)", async () => {
    mockStatus({
      stats: { images: 0, galleries: 0, roots: 0, users: 1 },
      scan_statuses: [
        { root_id: 1, gallery_id: 1, label: "A", absolute_path: "/a", enabled: true,
          status: "idle", last_scan_at: null, last_scan_status: null, last_scan_error: null },
        { root_id: 2, gallery_id: 1, label: "B", absolute_path: "/b", enabled: true,
          status: "queued", last_scan_at: null, last_scan_status: null, last_scan_error: null },
        { root_id: 3, gallery_id: 1, label: "C", absolute_path: "/c", enabled: true,
          status: "running", last_scan_at: null, last_scan_status: null, last_scan_error: null },
      ],
      recent_audit: [],
    })
    const w = mountView()
    await flushPromises()
    const html = w.html()
    // Every color class must appear somewhere in the rendered scan-list.
    expect(html).toContain("text-green-400")
    expect(html).toContain("text-yellow-400")
    expect(html).toContain("text-blue-400")
  })

  it("formats timestamps as YYYY-MM-DD HH:mm:ss", async () => {
    mockStatus({
      stats: { images: 0, galleries: 0, roots: 0, users: 1 },
      scan_statuses: [],
      recent_audit: [
        {
          id: 1,
          ts: 1_700_000_000,
          actor_user_id: null,
          actor_ip: "127.0.0.1",
          action: "login_success",
          target: null,
          detail: null,
        },
      ],
    })
    const w = mountView()
    await flushPromises()
    // Locale-agnostic shape check (exact digits depend on tz).
    expect(w.text()).toMatch(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/)
  })
})
