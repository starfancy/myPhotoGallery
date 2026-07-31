import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import LoginView from "../views/LoginView.vue"

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/login", component: LoginView },
      { path: "/galleries", component: { template: "<div>galleries</div>" } },
    ],
  })
}

async function mountView() {
  const router = makeRouter()
  await router.push("/login")
  const w = mount(LoginView, {
    global: { plugins: [createPinia(), router] },
  })
  await flushPromises()
  return w
}

function mockFetchOnce(response: unknown, status = 200) {
  return new Response(JSON.stringify(response), {
    status,
    headers: { "content-type": "application/json" },
  })
}

describe("LoginView (P4 access_scope)", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("renders the form with username and password fields", async () => {
    const w = await mountView()
    expect(w.find("input[autocomplete=username]").exists()).toBe(true)
    expect(w.find("input[autocomplete=current-password]").exists()).toBe(true)
  })

  it("shows access_scope_violation banner (amber) on 403", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockFetchOnce(
        { error: { code: "access_scope_violation", message: "LAN only" } },
        403,
      ),
    )
    vi.stubGlobal("fetch", fetchMock)

    const w = await mountView()
    await w.find("input[autocomplete=username]").setValue("lan_user")
    await w.find("input[autocomplete=current-password]").setValue("pw")
    await w.find("form").trigger("submit")
    await flushPromises()

    const html = w.html()
    expect(html).toContain("该账号仅限局域网访问")
    expect(html).toMatch(/amber/)
  })

  it("shows login_locked banner (yellow) on 423", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockFetchOnce(
        { error: { code: "login_locked", message: "too many" } },
        423,
      ),
    )
    vi.stubGlobal("fetch", fetchMock)

    const w = await mountView()
    await w.find("input[autocomplete=username]").setValue("u")
    await w.find("input[autocomplete=current-password]").setValue("pw")
    await w.find("form").trigger("submit")
    await flushPromises()

    const html = w.html()
    expect(html).toContain("登录尝试过多")
    expect(html).toMatch(/yellow/)
  })

  it("shows invalid_credentials banner (red) on 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      mockFetchOnce(
        { error: { code: "invalid_credentials", message: "wrong" } },
        401,
      ),
    )
    vi.stubGlobal("fetch", fetchMock)

    const w = await mountView()
    await w.find("input[autocomplete=username]").setValue("u")
    await w.find("input[autocomplete=current-password]").setValue("wrong")
    await w.find("form").trigger("submit")
    await flushPromises()

    const html = w.html()
    expect(html).toContain("用户名或密码错误")
    expect(html).toMatch(/red/)
  })
})
