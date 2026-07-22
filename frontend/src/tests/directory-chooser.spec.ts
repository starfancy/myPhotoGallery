import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import DirectoryChooser from "../components/DirectoryChooser.vue"

// Helper: return the JSON payload the next fetch() call should resolve to.
// Sets up a fresh mock so different tests can chain multiple responses.
function mockFetchQueue(responses: Array<{ body: unknown; status?: number }>) {
  const fn = vi.fn()
  for (const r of responses) {
    fn.mockResolvedValueOnce(
      new Response(JSON.stringify(r.body), {
        status: r.status ?? 200,
        headers: { "content-type": "application/json" },
      }),
    )
  }
  vi.stubGlobal("fetch", fn)
  return fn
}

const POSIX_HOME = {
  path: "/home/user",
  entries: [
    { name: "photos", path: "/home/user/photos", is_root: false },
    { name: "docs", path: "/home/user/docs", is_root: false },
  ],
  truncated: false,
}

const WIN_ROOT = {
  path: "",
  entries: [
    { name: "C:", path: "C:\\", is_root: true },
    { name: "D:", path: "D:\\", is_root: true },
  ],
  truncated: false,
}

describe("DirectoryChooser", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it("renders nothing when modelValue is false", () => {
    const w = mount(DirectoryChooser, {
      props: { modelValue: false },
    })
    expect(w.find('[role="dialog"]').exists()).toBe(false)
  })

  it("fetches initial directory on open and lists entries", async () => {
    const fetchMock = mockFetchQueue([{ body: POSIX_HOME }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    // Called browse-fs with the startPath.
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/admin/browse-fs")
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ path: "/home/user" })

    // Entries rendered.
    expect(w.text()).toContain("photos")
    expect(w.text()).toContain("docs")
  })

  it("builds POSIX breadcrumbs from the returned path", async () => {
    mockFetchQueue([{ body: POSIX_HOME }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    // Root pseudo-crumb + "home" + "user"
    const crumbs = w.findAll("button").filter((b) =>
      ["根", "home", "user"].includes(b.text()),
    )
    expect(crumbs.map((b) => b.text())).toContain("根")
    expect(crumbs.map((b) => b.text())).toContain("home")
    expect(crumbs.map((b) => b.text())).toContain("user")
  })

  it("builds Windows breadcrumbs from a backslash path", async () => {
    mockFetchQueue([
      {
        body: {
          path: "C:\\Users\\me",
          entries: [],
          truncated: false,
        },
      },
    ])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "C:\\Users\\me" },
    })
    await flushPromises()

    const btns = w.findAll("button").map((b) => b.text())
    expect(btns).toContain("C:")
    expect(btns).toContain("Users")
    expect(btns).toContain("me")
  })

  it("shows drive letters at Windows root (path='')", async () => {
    mockFetchQueue([{ body: WIN_ROOT }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "" },
    })
    await flushPromises()

    expect(w.text()).toContain("C:")
    expect(w.text()).toContain("D:")

    // Confirm button is disabled at root (no real path to select).
    const buttons = w.findAll("button").filter((b) => b.text() === "确认")
    expect(buttons.length).toBe(1)
    expect(buttons[0].attributes("disabled")).toBeDefined()
  })

  it("single-clicking a drive letter does NOT enable confirm", async () => {
    // Regression: previously any single-click populated `selected`, which
    // let the user confirm a bare drive root (e.g. "C:\\") as a gallery
    // root by accident. is_root entries are now navigation-only.
    mockFetchQueue([{ body: WIN_ROOT }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "" },
    })
    await flushPromises()

    const driveBtn = w.findAll("button").find((b) => b.text().includes("C:"))!
    await driveBtn.trigger("click")
    const confirmBtn = w.findAll("button").find((b) => b.text() === "确认")!
    expect(confirmBtn.attributes("disabled")).toBeDefined()
  })

  it("emits confirm with the current directory when nothing is selected", async () => {
    mockFetchQueue([{ body: POSIX_HOME }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    const confirmBtn = w.findAll("button").find((b) => b.text() === "确认")!
    expect(confirmBtn.attributes("disabled")).toBeUndefined()
    await confirmBtn.trigger("click")
    expect(w.emitted("confirm")).toBeDefined()
    expect(w.emitted("confirm")![0]).toEqual(["/home/user"])
    expect(w.emitted("update:modelValue")).toBeDefined()
    expect(w.emitted("update:modelValue")![0]).toEqual([false])
  })

  it("emits confirm with selected entry path when an entry is clicked", async () => {
    mockFetchQueue([{ body: POSIX_HOME }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    const entryBtn = w.findAll("button").find((b) => b.text().includes("photos"))!
    await entryBtn.trigger("click")

    const confirmBtn = w.findAll("button").find((b) => b.text() === "确认")!
    await confirmBtn.trigger("click")

    expect(w.emitted("confirm")![0]).toEqual(["/home/user/photos"])
  })

  it("double-clicking an entry navigates into it", async () => {
    const fetchMock = mockFetchQueue([
      { body: POSIX_HOME },
      {
        body: {
          path: "/home/user/photos",
          entries: [{ name: "vacation", path: "/home/user/photos/vacation", is_root: false }],
          truncated: false,
        },
      },
    ])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    const entryBtn = w.findAll("button").find((b) => b.text().includes("photos"))!
    await entryBtn.trigger("dblclick")
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, init] = fetchMock.mock.calls[1]
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      path: "/home/user/photos",
    })
    expect(w.text()).toContain("vacation")
  })

  it("shows truncation warning when server returns truncated=true", async () => {
    mockFetchQueue([
      {
        body: {
          path: "/big",
          entries: [{ name: "sub", path: "/big/sub", is_root: false }],
          truncated: true,
        },
      },
    ])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/big" },
    })
    await flushPromises()

    expect(w.text()).toContain("5000")
  })

  it("shows API error message when browse-fs returns 4xx", async () => {
    mockFetchQueue([
      {
        status: 400,
        body: { error: { code: "path_invalid", message: "no dots allowed" } },
      },
    ])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/oops/.." },
    })
    await flushPromises()

    expect(w.text()).toContain("no dots allowed")
  })

  it("cancel button emits update:modelValue=false without confirm", async () => {
    mockFetchQueue([{ body: POSIX_HOME }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    const cancelBtn = w.findAll("button").find((b) => b.text() === "取消")!
    await cancelBtn.trigger("click")

    expect(w.emitted("update:modelValue")).toBeDefined()
    expect(w.emitted("update:modelValue")![0]).toEqual([false])
    expect(w.emitted("confirm")).toBeUndefined()
  })

  it("clicking backdrop closes without confirm", async () => {
    mockFetchQueue([{ body: POSIX_HOME }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    // The backdrop is the outermost fixed div with the click.self modifier.
    const backdrop = w.find(".fixed.inset-0")
    await backdrop.trigger("click")
    expect(w.emitted("update:modelValue")).toBeDefined()
    expect(w.emitted("confirm")).toBeUndefined()
  })

  it("manual path input navigates on Enter", async () => {
    const fetchMock = mockFetchQueue([
      { body: POSIX_HOME },
      {
        body: {
          path: "/var",
          entries: [{ name: "log", path: "/var/log", is_root: false }],
          truncated: false,
        },
      },
    ])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()

    const input = w.find("input")
    await input.setValue("/var")
    await input.trigger("keydown.enter")
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [, init] = fetchMock.mock.calls[1]
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ path: "/var" })
  })

  it("reopening after close re-fetches the startPath", async () => {
    const fetchMock = mockFetchQueue([{ body: POSIX_HOME }, { body: POSIX_HOME }])
    const w = mount(DirectoryChooser, {
      props: { modelValue: true, startPath: "/home/user" },
    })
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await w.setProps({ modelValue: false })
    await flushPromises()
    await w.setProps({ modelValue: true })
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
