import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminGalleryEdit from "../views/AdminGalleryEdit.vue"

const GALLERY = {
  id: 1,
  name: "Home",
  description: "Family photos",
  roots: [
    {
      id: 10,
      label: "Main",
      absolute_path: "/photos/main",
      enabled: true,
      image_count: 42,
      status: "idle",
      last_scan_at: 1_700_000_000,
      last_scan_status: "ok",
      last_scan_error: null,
    },
    {
      id: 11,
      label: "Broken",
      absolute_path: "/gone",
      enabled: true,
      image_count: 0,
      status: "idle",
      last_scan_at: null,
      last_scan_status: "error",
      last_scan_error: "path not found",
    },
  ],
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/admin/galleries/:gid", component: AdminGalleryEdit },
    ],
  })
}

function mockFetchOnce(response: unknown, status = 200) {
  return new Response(JSON.stringify(response), {
    status,
    headers: { "content-type": "application/json" },
  })
}

function mockFetchSequence(...responses: Array<{ body: unknown; status?: number }>) {
  const fn = vi.fn()
  for (const r of responses) {
    fn.mockResolvedValueOnce(mockFetchOnce(r.body, r.status ?? 200))
  }
  vi.stubGlobal("fetch", fn)
  return fn
}

async function mountView() {
  const router = makeRouter()
  await router.push("/admin/galleries/1")
  const w = mount(AdminGalleryEdit, {
    global: {
      plugins: [createPinia(), router],
    },
  })
  await flushPromises()
  return w
}

describe("AdminGalleryEdit", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it("shows loading state then renders gallery info and roots", async () => {
    mockFetchSequence({ body: GALLERY })
    const w = await mountView()

    // Gallery name in header
    expect(w.text()).toContain("Home")
    // Root labels and paths
    expect(w.text()).toContain("Main")
    expect(w.text()).toContain("/photos/main")
    expect(w.text()).toContain("42 张")
    expect(w.text()).toContain("Broken")
    expect(w.text()).toContain("/gone")
    expect(w.text()).toContain("path not found")
    // Description input's current value (v-model, not a text node)
    const descInput = w.findAll("input")[1]
    expect((descInput.element as HTMLInputElement).value).toBe("Family photos")
  })

  it("shows error message on API failure", async () => {
    mockFetchSequence({ body: { error: { code: "not_found", message: "gallery not found" } }, status: 404 })
    const w = await mountView()
    expect(w.text()).toContain("gallery not found")
  })

  it("save button sends PATCH with changed fields", async () => {
    // First call: initial loadGallery
    mockFetchSequence({ body: GALLERY })
    const w = await mountView()

    // Now set up the PATCH call mock: the save button calls apiPatch
    const fetchFn = vi.fn()
    fetchFn.mockResolvedValueOnce(
      mockFetchOnce({ id: 1, name: "Home", description: "Updated desc" }),
    )
    vi.stubGlobal("fetch", fetchFn)

    const descInput = w.findAll("input")[1]
    await descInput.setValue("Updated desc")
    const saveBtn = w.findAll("button").find((b) => b.text() === "保存")!
    saveBtn.trigger("click")
    await flushPromises()

    expect(fetchFn).toHaveBeenCalledTimes(1)
    const [url, init] = fetchFn.mock.calls[0]
    expect(url).toBe("/api/admin/galleries/1")
    expect(init.method).toBe("PATCH")
    expect(JSON.parse(init.body)).toEqual({ description: "Updated desc" })
    expect(w.text()).toContain("已保存")
  })

  it("rescan button sends POST and reloads", async () => {
    // Initial load + rescan POST + reload GET
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(mockFetchOnce(GALLERY))      // initial loadGallery
      .mockResolvedValueOnce(mockFetchOnce({ status: "queued" }))  // rescan POST
      .mockResolvedValueOnce(mockFetchOnce(GALLERY))      // reload after rescan
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const rescanBtns = w.findAll("button").filter((b) => b.text() === "重扫")
    rescanBtns[0].trigger("click")
    await flushPromises()

    // Find the rescan call in the fetch history
    const rescanCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/galleries/1/roots/10/rescan",
    )
    expect(rescanCall).toBeDefined()
    expect(rescanCall[1].method).toBe("POST")
  })

  it("remove button shows confirm dialog then sends DELETE", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(mockFetchOnce(GALLERY))                       // initial loadGallery
      .mockResolvedValueOnce(new Response(null, { status: 204 }))          // DELETE
      .mockResolvedValueOnce(mockFetchOnce(GALLERY))                       // reload after delete
    vi.stubGlobal("fetch", fetchFn)
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const w = await mountView()

    const removeBtns = w.findAll("button").filter((b) => b.text() === "移除")
    removeBtns[0].trigger("click")
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    const deleteCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/galleries/1/roots/10",
    )
    expect(deleteCall).toBeDefined()
    expect(deleteCall[1].method).toBe("DELETE")
  })

  it("shows the add-root (+) card and opens DirectoryChooser modal", async () => {
    mockFetchSequence({ body: GALLERY })
    const w = await mountView()

    const addCard = w.findAll("button").find((b) => b.text() === "+")
    expect(addCard).toBeDefined()
    await addCard!.trigger("click")
    // The DirectoryChooser modal should now be visible.
    expect(w.text()).toContain("选择目录")
  })

  it("renders processed/total, percent and current path for a running root", async () => {
    const running = {
      ...GALLERY,
      roots: [
        {
          ...GALLERY.roots[0],
          status: "running",
          phase: "hashing",
          total_files: 10,
          processed_files: 4,
          current_path: "vacation/001.jpg",
          started_at: 1_700_000_000,
        },
      ],
    }
    mockFetchSequence({ body: running })
    const w = await mountView()

    expect(w.text()).toContain("4 / 10")
    expect(w.text()).toContain("40%")
    expect(w.text()).toContain("vacation/001.jpg")
    // progress bar exposes its percentage for assistive tech / tests
    const bar = w.find('[role="progressbar"]')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes("aria-valuenow")).toBe("40")
  })

  it("polls every 2s while a scan is running and stops when idle", async () => {
    vi.useFakeTimers()
    const running = {
      ...GALLERY,
      roots: [{ ...GALLERY.roots[0], status: "running", total_files: 10, processed_files: 1 }],
    }
    const idle = GALLERY
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(mockFetchOnce(running)) // onMounted load
      .mockResolvedValueOnce(mockFetchOnce(running)) // first poll
      .mockResolvedValueOnce(mockFetchOnce(idle))    // second poll -> idle
    vi.stubGlobal("fetch", fetchFn)

    const w = await mountView()
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(2)

    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(3)

    // All roots idle -> no further polling.
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(3)

    w.unmount()
    // After unmount, a timer (if any leaked) must not fire another fetch.
    vi.advanceTimersByTime(5000)
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(3)
  })

  it("silent poll does not clobber in-progress name edits", async () => {
    vi.useFakeTimers()
    const running = {
      ...GALLERY,
      roots: [{ ...GALLERY.roots[0], status: "running", total_files: 10, processed_files: 2 }],
    }
    const polled = {
      ...running,
      name: "Renamed By Server",
      description: "changed by poll",
      roots: [{ ...running.roots[0], processed_files: 3 }],
    }
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(mockFetchOnce(running))
      .mockResolvedValueOnce(mockFetchOnce(polled))
    vi.stubGlobal("fetch", fetchFn)

    const w = await mountView()
    const nameInput = w.findAll("input")[0]
    await nameInput.setValue("I am typing this")

    vi.advanceTimersByTime(2000)
    await flushPromises()

    // User's in-progress edit survives the background poll.
    expect((nameInput.element as HTMLInputElement).value).toBe("I am typing this")
    // The header/gallery title may update, but the edit input is untouched.
    w.unmount()
  })
})
