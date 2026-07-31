import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { createMemoryHistory, createRouter } from "vue-router"
import AdminUsers from "../views/AdminUsers.vue"
import { useAuthStore, type AuthUser } from "../stores/auth"

const routes = [
  { path: "/admin/users", component: { template: "<div />" } },
  { path: "/admin", component: { template: "<div />" } },
]

function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

function seedAuth(user: AuthUser | null) {
  const auth = useAuthStore()
  auth.user = user
}

interface FetchRecord {
  url: string
  init?: RequestInit
  body?: any
}

function setupFetchMock(handlers: Record<string, (rec: FetchRecord) => any>) {
  const calls: FetchRecord[] = []
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    const rec: FetchRecord = { url, init }
    if (init?.body) rec.body = JSON.parse(init.body as string)
    calls.push(rec)
    for (const [pat, h] of Object.entries(handlers)) {
      if (url.includes(pat)) {
        const payload = h(rec)
        return new Response(JSON.stringify(payload.data), {
          status: payload.status ?? 200,
          headers: { "content-type": "application/json" },
        })
      }
    }
    return new Response(JSON.stringify({}), { status: 200 })
  })
  vi.stubGlobal("fetch", mock)
  return { mock, calls }
}

const ADMIN_USER: AuthUser = {
  id: 1,
  username: "admin",
  role: "admin",
  access_scope: "remote_allowed",
}

const SAMPLE_USERS = [
  {
    id: 1, username: "admin", role: "admin", access_scope: "remote_allowed",
    enabled: 1, gallery_count: 2, last_login_at: 1_700_000_000, created_at: 1_600_000_000,
  },
  {
    id: 2, username: "alice", role: "viewer", access_scope: "lan_only",
    enabled: 1, gallery_count: 1, last_login_at: null, created_at: 1_650_000_000,
  },
  {
    id: 3, username: "bob", role: "viewer", access_scope: "remote_allowed",
    enabled: 0, gallery_count: 0, last_login_at: 1_690_000_000, created_at: 1_660_000_000,
  },
]

const SAMPLE_GALLERIES = [
  { id: 10, name: "Vacation" },
  { id: 20, name: "Family" },
]

async function mountView() {
  setActivePinia(createPinia())
  seedAuth(ADMIN_USER)
  const router = makeRouter()
  await router.push("/admin/users")
  const w = mount(AdminUsers, { global: { plugins: [router] } })
  await flushPromises()
  return w
}

describe("AdminUsers (P4)", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("loads and renders the user table", async () => {
    setupFetchMock({
      "/api/admin/users": () => ({ data: SAMPLE_USERS }),
      "/api/admin/galleries": () => ({ data: SAMPLE_GALLERIES }),
    })
    const w = await mountView()
    expect(w.text()).toContain("admin")
    expect(w.text()).toContain("alice")
    expect(w.text()).toContain("bob")
    expect(w.text()).toContain("3 个用户")
  })

  it("shows role and access_scope badges", async () => {
    setupFetchMock({
      "/api/admin/users": () => ({ data: SAMPLE_USERS }),
      "/api/admin/galleries": () => ({ data: [] }),
    })
    const w = await mountView()
    const html = w.html()
    expect(html).toContain("管理员")
    expect(html).toContain("访客")
    expect(html).toContain("LAN")
    expect(html).toContain("远程")
  })

  it("shows loading state before fetch resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
    setActivePinia(createPinia())
    seedAuth(ADMIN_USER)
    const router = makeRouter()
    return router.push("/admin/users").then(() => {
      const w = mount(AdminUsers, { global: { plugins: [router] } })
      expect(w.text()).toContain("加载中")
    })
  })

  it("opens the create modal on 新建用户 click", async () => {
    setupFetchMock({
      "/api/admin/users": () => ({ data: [] }),
      "/api/admin/galleries": () => ({ data: SAMPLE_GALLERIES }),
    })
    const w = await mountView()
    await w.find('[data-testid="new-user-btn"]').trigger("click")
    expect(w.find('[data-testid="user-modal"]').exists()).toBe(true)
  })

  it("submits create with explicit password and gallery_ids (viewer)", async () => {
    const { calls } = setupFetchMock({
      "/api/admin/users": (rec) => {
        if (rec.init?.method === "GET") return { data: SAMPLE_USERS }
        return { data: { id: 99, username: rec.body.username } }
      },
      "/api/admin/galleries": () => ({ data: SAMPLE_GALLERIES }),
    })
    const w = await mountView()
    await w.find('[data-testid="new-user-btn"]').trigger("click")
    await w.find('[data-testid="modal-username"]').setValue("carol")
    await w.find('[data-testid="modal-password"]').setValue("secret123")
    await w.find('[data-testid="modal-role-viewer"]').setValue()
    // gallery checkboxes
    await w.find('[data-testid="modal-gallery-10"]').setValue()
    await w.find('[data-testid="modal-gallery-20"]').setValue()
    await w.find('[data-testid="modal-submit"]').trigger("click")
    await flushPromises()

    const create = calls.find(
      (c) => c.url.includes("/api/admin/users") && c.init?.method === "POST",
    )
    expect(create).toBeDefined()
    expect(create!.body).toMatchObject({
      username: "carol",
      role: "viewer",
      access_scope: "remote_allowed",
      password: "secret123",
      gallery_ids: [10, 20],
    })
  })

  it("reveals initial_password when admin leaves password blank", async () => {
    setupFetchMock({
      "/api/admin/users": (rec) => {
        if (rec.init?.method === "GET") return { data: SAMPLE_USERS }
        return { data: { id: 99, username: "carol", initial_password: "AUTOgen12!!" } }
      },
      "/api/admin/galleries": () => ({ data: [] }),
    })
    const w = await mountView()
    await w.find('[data-testid="new-user-btn"]').trigger("click")
    await w.find('[data-testid="modal-username"]').setValue("carol")
    // leave password blank
    await w.find('[data-testid="modal-submit"]').trigger("click")
    await flushPromises()
    expect(w.find('[data-testid="reveal-pw-modal"]').exists()).toBe(true)
    expect(w.find('[data-testid="reveal-pw-value"]').text()).toContain("AUTOgen12")
  })

  it("opening edit modal fetches user detail and pre-fills gallery_ids", async () => {
    setupFetchMock({
      "/api/admin/users": (rec) => {
        // GET list vs GET detail-by-id
        if (rec.init?.method === "GET" && rec.url.endsWith("/api/admin/users")) {
          return { data: SAMPLE_USERS }
        }
        if (rec.url.includes("/api/admin/users/2")) {
          return { data: { ...SAMPLE_USERS[1], gallery_ids: [10] } }
        }
        return { data: {} }
      },
      "/api/admin/galleries": () => ({ data: SAMPLE_GALLERIES }),
    })
    const w = await mountView()
    await w.find('[data-testid="edit-btn-alice"]').trigger("click")
    await flushPromises()
    // wait a bit more for the detail fetch
    await flushPromises()
    const modal = w.find('[data-testid="user-modal"]')
    expect(modal.exists()).toBe(true)
    // gallery checkbox 10 should be checked
    const cb = w.find('[data-testid="modal-gallery-10"]')
      .element as HTMLInputElement
    expect(cb.checked).toBe(true)
  })

  it("toggles enable/disable on click (PATCH enabled)", async () => {
    const { calls } = setupFetchMock({
      "/api/admin/users": () => ({ data: SAMPLE_USERS }),
      "/api/admin/galleries": () => ({ data: [] }),
    })
    const w = await mountView()
    await w.find('[data-testid="toggle-btn-alice"]').trigger("click")
    await flushPromises()
    const patch = calls.find(
      (c) => c.url.includes("/api/admin/users/2") && c.init?.method === "PATCH",
    )
    expect(patch).toBeDefined()
    expect(patch!.body).toEqual({ enabled: 0 })
  })

  it("resets password via modal and reveals new password", async () => {
    const { calls } = setupFetchMock({
      "/reset-password": () => ({ data: { new_password: "RESETgen123" } }),
      "/api/admin/users": () => ({ data: SAMPLE_USERS }),
      "/api/admin/galleries": () => ({ data: [] }),
    })
    const w = await mountView()
    await w.find('[data-testid="resetpw-btn-alice"]').trigger("click")
    await flushPromises()
    await w.find('[data-testid="reset-pw-submit"]').trigger("click")
    await flushPromises()
    await flushPromises()
    const req = calls.find((c) => c.url.includes("/reset-password"))
    expect(req).toBeDefined()
    expect(w.find('[data-testid="reveal-pw-modal"]').exists()).toBe(true)
    expect(w.find('[data-testid="reveal-pw-value"]').text()).toContain("RESETgen123")
  })

  it("delete asks for username confirmation and then sends DELETE", async () => {
    const promptMock = vi.spyOn(window, "prompt").mockReturnValue("alice")

    const { calls } = setupFetchMock({
      "/api/admin/users": () => ({ data: SAMPLE_USERS }),
      "/api/admin/galleries": () => ({ data: [] }),
    })
    const w = await mountView()
    await w.find('[data-testid="delete-btn-alice"]').trigger("click")
    await flushPromises()
    expect(promptMock).toHaveBeenCalled()
    const del = calls.find(
      (c) => c.url.includes("/api/admin/users/2") && c.init?.method === "DELETE",
    )
    expect(del).toBeDefined()
    promptMock.mockRestore()
  })

  it("delete cancelled when confirmation does not match", async () => {
    const promptMock = vi.spyOn(window, "prompt").mockReturnValue("wrong_name")

    const { calls } = setupFetchMock({
      "/api/admin/users": () => ({ data: SAMPLE_USERS }),
      "/api/admin/galleries": () => ({ data: [] }),
    })
    const w = await mountView()
    await w.find('[data-testid="delete-btn-alice"]').trigger("click")
    await flushPromises()
    const del = calls.find(
      (c) => c.url.includes("/api/admin/users/2") && c.init?.method === "DELETE",
    )
    expect(del).toBeUndefined()
    promptMock.mockRestore()
  })

  it("cannot disable self — toggle button is disabled on current user row", async () => {
    setupFetchMock({
      "/api/admin/users": () => ({ data: SAMPLE_USERS }),
      "/api/admin/galleries": () => ({ data: [] }),
    })
    const w = await mountView()
    const btn = w.find('[data-testid="toggle-btn-admin"]')
      .element as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    const delBtn = w.find('[data-testid="delete-btn-admin"]')
      .element as HTMLButtonElement
    expect(delBtn.disabled).toBe(true)
  })
})
