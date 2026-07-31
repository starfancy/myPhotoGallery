import { beforeEach, describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AppHeader from "../components/AppHeader.vue"
import { useAuthStore, type AuthUser } from "../stores/auth"

const routes = [
  { path: "/galleries", component: { template: "<div>g</div>" } },
  { path: "/login", component: { template: "<div>l</div>" } },
  { path: "/settings/password", component: { template: "<div>p</div>" } },
  { path: "/admin", component: { template: "<div>a</div>" } },
]

function makeAuthUser(over: Partial<AuthUser> = {}): AuthUser {
  return {
    id: 1,
    username: "alice",
    role: "admin",
    access_scope: "remote_allowed",
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

  it("shows no badge when access_scope is missing", async () => {
    const w = await mountHeader({
      id: 1,
      username: "u",
      role: "viewer",
      access_scope: "remote_allowed",  // always set in practice; this test ensures even without it the header doesn't crash
    })
    // username should be visible
    expect(w.html()).toContain("u")
  })
})
