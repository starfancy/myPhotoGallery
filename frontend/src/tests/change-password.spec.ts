import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import ChangePasswordView from "../views/ChangePasswordView.vue"

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/settings/password", component: ChangePasswordView },
    ],
  })
}

function mockFetchOnce(response: unknown, status = 200) {
  return new Response(JSON.stringify(response), {
    status,
    headers: { "content-type": "application/json" },
  })
}

async function mountView() {
  const router = makeRouter()
  await router.push("/settings/password")
  const w = mount(ChangePasswordView, {
    global: { plugins: [createPinia(), router] },
  })
  await flushPromises()
  return w
}

describe("ChangePasswordView", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("renders the form with all fields", async () => {
    const w = await mountView()
    expect(w.text()).toContain("当前密码")
    expect(w.text()).toContain("新密码")
    expect(w.text()).toContain("确认新密码")
    expect(w.text()).toContain("修改密码")
  })

  it("disables submit when passwords mismatch", async () => {
    const w = await mountView()
    const inputs = w.findAll("input")
    await inputs[0].setValue("oldpass")
    await inputs[1].setValue("newpass123")
    await inputs[2].setValue("different")
    await flushPromises()

    expect(w.text()).toContain("两次输入的密码不一致")
    // The submit button should be disabled
    const form = w.find("form")
    const btn = form.find("button[type='submit']")
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it("disables submit when new password is too short", async () => {
    const w = await mountView()
    const inputs = w.findAll("input")
    await inputs[0].setValue("oldpass")
    await inputs[1].setValue("short")
    await inputs[2].setValue("short")
    await flushPromises()

    const form = w.find("form")
    const btn = form.find("button[type='submit']")
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it("sends POST with correct body and shows success", async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchFn)

    const w = await mountView()
    const inputs = w.findAll("input")
    await inputs[0].setValue("oldpass")
    await inputs[1].setValue("newpass123")
    await inputs[2].setValue("newpass123")
    await flushPromises()

    const form = w.find("form")
    const btn = form.find("button[type='submit']")
    expect((btn.element as HTMLButtonElement).disabled).toBe(false)
    await form.trigger("submit")
    await flushPromises()

    expect(fetchFn).toHaveBeenCalledTimes(1)
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe("/api/auth/change-password")
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({
      old_password: "oldpass",
      new_password: "newpass123",
    })
    expect(w.text()).toContain("密码已修改")
  })

  it("shows error on wrong current password", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "invalid_credentials", message: "current password is incorrect" } }),
          { status: 403, headers: { "content-type": "application/json" } },
        ),
      ),
    )

    const w = await mountView()
    const inputs = w.findAll("input")
    await inputs[0].setValue("wrong")
    await inputs[1].setValue("newpass123")
    await inputs[2].setValue("newpass123")
    await flushPromises()

    const form = w.find("form")
    await form.trigger("submit")
    await flushPromises()

    expect(w.text()).toContain("current password is incorrect")
  })

  it("shows error when new password is too weak", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "password_too_weak", message: "password must be at least 8 characters" } }),
          { status: 422, headers: { "content-type": "application/json" } },
        ),
      ),
    )

    const w = await mountView()
    const inputs = w.findAll("input")
    await inputs[0].setValue("oldpass")
    await inputs[1].setValue("abcdefgh")
    await inputs[2].setValue("abcdefgh")
    await flushPromises()

    const form = w.find("form")
    await form.trigger("submit")
    await flushPromises()

    expect(w.text()).toContain("password must be at least 8 characters")
  })

  it("clears form fields after successful change", async () => {
    const fetchFn = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchFn)

    const w = await mountView()
    const inputs = w.findAll("input")
    await inputs[0].setValue("oldpass")
    await inputs[1].setValue("newpass123")
    await inputs[2].setValue("newpass123")
    await flushPromises()

    const form = w.find("form")
    await form.trigger("submit")
    await flushPromises()

    // All fields should be cleared after success
    expect((inputs[0].element as HTMLInputElement).value).toBe("")
    expect((inputs[1].element as HTMLInputElement).value).toBe("")
    expect((inputs[2].element as HTMLInputElement).value).toBe("")
  })
})