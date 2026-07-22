import { beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import {
  createMemoryHistory,
  createRouter,
  type RouteRecordRaw,
  type Router,
} from "vue-router"
import { useAuthStore, type AuthUser } from "../stores/auth"
import { authGuard } from "../router"
import AppHeader from "../components/AppHeader.vue"

// A minimal set of routes that mirrors router.ts's meta flags. We can't
// import the production `router` because it uses createWebHistory() (browser
// history) and would try to fetchMe() on the first navigation.
const testRoutes: RouteRecordRaw[] = [
  { path: "/", redirect: "/galleries" },
  { path: "/login", component: { template: "<div>login</div>" }, meta: { public: true } },
  { path: "/galleries", component: { template: "<div>galleries</div>" } },
  {
    path: "/admin",
    component: { template: "<div>admin</div>" },
    meta: { requiresAdmin: true },
  },
  {
    path: "/admin/galleries/:gid",
    component: { template: "<div>admin gallery</div>" },
    meta: { requiresAdmin: true },
  },
]

function makeRouter(): Router {
  const r = createRouter({ history: createMemoryHistory(), routes: testRoutes })
  // Wire the SAME authGuard the production router uses. Tests seed the store
  // directly so fetchMe() is not triggered.
  r.beforeEach((to) => authGuard(to, useAuthStore()))
  return r
}

function seedUser(role: "admin" | "viewer" | null) {
  const auth = useAuthStore()
  if (role === null) {
    auth.user = null
  } else {
    auth.user = {
      id: 1,
      username: "u",
      role,
      access_scope: "lan_only",
    } as AuthUser
  }
}

describe("authGuard", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // Stub fetch so the guard's fetchMe() call doesn't attempt real network
    // I/O. We return 401 to simulate "not logged in"; tests that seed a user
    // trip the null-check first and never reach the fetch.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "unauthenticated", message: "no session" } }),
          { status: 401, headers: { "content-type": "application/json" } },
        ),
      ),
    )
  })

  it("redirects unauthenticated user to /login", async () => {
    const r = makeRouter()
    seedUser(null)
    await r.push("/admin")
    expect(r.currentRoute.value.path).toBe("/login")
    expect(r.currentRoute.value.query.next).toBe("/admin")
  })

  it("redirects viewer away from /admin to /galleries", async () => {
    const r = makeRouter()
    seedUser("viewer")
    await r.push("/admin")
    expect(r.currentRoute.value.path).toBe("/galleries")
  })

  it("redirects viewer away from /admin/galleries/:gid", async () => {
    const r = makeRouter()
    seedUser("viewer")
    await r.push("/admin/galleries/42")
    expect(r.currentRoute.value.path).toBe("/galleries")
  })

  it("permits admin to visit /admin", async () => {
    const r = makeRouter()
    seedUser("admin")
    await r.push("/admin")
    expect(r.currentRoute.value.path).toBe("/admin")
  })

  it("permits admin to visit /admin/galleries/:gid", async () => {
    const r = makeRouter()
    seedUser("admin")
    await r.push("/admin/galleries/7")
    expect(r.currentRoute.value.path).toBe("/admin/galleries/7")
    expect(r.currentRoute.value.params.gid).toBe("7")
  })

  it("permits viewer to visit /galleries (no admin meta)", async () => {
    const r = makeRouter()
    seedUser("viewer")
    await r.push("/galleries")
    expect(r.currentRoute.value.path).toBe("/galleries")
  })

  it("permits public routes without auth", async () => {
    const r = makeRouter()
    seedUser(null)
    await r.push("/login")
    expect(r.currentRoute.value.path).toBe("/login")
  })
})

describe("AppHeader admin link", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function mountHeader() {
    // Mount with a real memory-history router so useRouter() resolves and
    // <router-link> renders as an <a> without stubbing.
    const r = makeRouter()
    return mount(AppHeader, {
      global: {
        plugins: [r],
      },
    })
  }

  it("shows 管理 link for admin users", () => {
    seedUser("admin")
    const w = mountHeader()
    const link = w.find('a[href="/admin"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain("管理")
  })

  it("hides 管理 link for viewer users", () => {
    seedUser("viewer")
    const w = mountHeader()
    expect(w.find('a[href="/admin"]').exists()).toBe(false)
  })

  it("hides 管理 link when logged out", () => {
    seedUser(null)
    const w = mountHeader()
    expect(w.find('a[href="/admin"]').exists()).toBe(false)
  })
})
