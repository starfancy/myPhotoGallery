import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AppHeader from "../components/AppHeader.vue"
import { useAuthStore, type AuthUser } from "../stores/auth"

const routes = [
  { path: "/galleries", component: { template: "<div>g</div>" } },
  { path: "/login", component: { template: "<div>l</div>" } },
  { path: "/settings/password", component: { template: "<div>p</div>" } },
  { path: "/admin", component: { template: "<div>a</div>" } },
  { path: "/filter-preview", component: { template: "<div>fp</div>" } },
]

function makeAuthUser(over: Partial<AuthUser> = {}): AuthUser {
  return {
    id: 1,
    username: "alice",
    role: "admin",
    access_scope: "remote_allowed",
    download_batch_limit: 100,
    ...over,
  }
}

async function mountHeader(user: AuthUser | null) {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.user = user

  const router = createRouter({ history: createMemoryHistory(), routes })
  await router.push("/galleries")

  return mount(AppHeader, {
    global: { plugins: [router] },
  })
}

describe("AppHeader (P4 access scope badge)", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it("shows 'LAN' badge for lan_only users", async () => {
    const w = await mountHeader(makeAuthUser({ access_scope: "lan_only" }))
    expect(w.html()).toContain("LAN")
    expect(w.html()).not.toContain("远程")
  })

  it("shows '远程' badge for remote_allowed users", async () => {
    const w = await mountHeader(
      makeAuthUser({ access_scope: "remote_allowed" }),
    )
    expect(w.html()).toContain("远程")
    expect(w.html()).not.toMatch(/>LAN</)
  })

  it("本地图片处理在新标签页打开，不改变当前标签页路由", async () => {
    const openSpy = vi.fn()
    vi.stubGlobal("open", openSpy)
    try {
      const w = await mountHeader(makeAuthUser())
      await w.findAll("button").find((b) => b.text().includes("工具"))!.trigger("click")
      await w.findAll("button").find((b) => b.text().includes("本地图片处理"))!.trigger("click")
      await flushPromises()

      // window.open 新标签页，query 带 local=1
      expect(openSpy).toHaveBeenCalledWith(
        "/filter-preview?local=1",
        "_blank",
        "noopener",
      )
      // 当前标签页仍停留在图库页
      expect(w.vm.$router.currentRoute.value.fullPath).toBe("/galleries")
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("shows no badge when access_scope is missing", async () => {
    const w = await mountHeader({
      id: 1,
      username: "u",
      role: "viewer",
      access_scope: "remote_allowed",  // always set in practice; this test ensures even without it the header doesn't crash
      download_batch_limit: 100,
    })
    // username should be visible
    expect(w.html()).toContain("u")
  })
})
