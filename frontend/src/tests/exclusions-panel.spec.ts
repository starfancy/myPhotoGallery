import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminGalleryEdit from "../views/AdminGalleryEdit.vue"
import DirectoryChooser from "../components/DirectoryChooser.vue"
import { formatDateTime } from "../utils/datetime"

const GALLERY = {
  id: 1,
  name: "Home",
  description: null,
  roots: [{
    id: 10,
    label: "Main",
    absolute_path: "/photos/main",
    enabled: true,
    image_count: 0,
    status: "idle",
    last_scan_at: null,
    last_scan_status: "ok",
    last_scan_error: null,
  }],
}

const EXCLUSIONS = {
  root_id: 10,
  entries: [{
    id: 55,
    relative_path: "exports",
    reason: "临时",
    excluded_by: 1,
    excluded_by_username: "admin",
    excluded_at: 1_782_600_000,
  }],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/galleries/:gid", component: AdminGalleryEdit }],
  })
  await router.push("/admin/galleries/1")
  const w = mount(AdminGalleryEdit, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return w
}

describe("AdminGalleryEdit exclusions panel", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("loads and shows exclusions lazily", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))      // gallery detail
      .mockResolvedValueOnce(json(EXCLUSIONS))   // exclusions GET
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()

    expect(w.text()).toContain("exports")
    expect(w.text()).toContain("admin")
    expect(w.text()).toContain(`排除于 ${formatDateTime(EXCLUSIONS.entries[0].excluded_at)}`)
    const getCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/galleries/1/roots/10/exclusions",
    )
    expect(getCall?.[1].method).toBe("GET")
  })

  it("shows empty state when no exclusions", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))
      .mockResolvedValueOnce(json({ root_id: 10, entries: [] }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("尚未排除任何目录")
  })

  it("removing an exclusion confirms, DELETEs, and reloads", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))
      .mockResolvedValueOnce(json(EXCLUSIONS))
      .mockResolvedValueOnce(new Response(null, { status: 204 })) // DELETE
      .mockResolvedValueOnce(json(GALLERY))                       // loadGallery
      .mockResolvedValueOnce(json({ root_id: 10, entries: [] })) // exclusions reload
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()

    await w.findAll("button").find((b) => b.text() === "解除")!.trigger("click")
    await flushPromises()

    const delCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) =>
        c[0] === "/api/admin/galleries/1/roots/10/exclusions/55",
    )
    expect(delCall?.[1].method).toBe("DELETE")
    expect(w.text()).toContain("尚未排除任何目录")
  })

  it("add flow: chooser is confined to root, confirm POSTs absolute_path", async () => {
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("备注"))
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))       // gallery
      .mockResolvedValueOnce(json(EXCLUSIONS))    // exclusions GET (panel open below)
      .mockResolvedValueOnce(json({              // browse-fs when chooser opens
        path: "/photos/main", entries: [], truncated: false,
      }))
      .mockResolvedValueOnce(json({              // POST exclusion
        id: 56,
        relative_path: "exports",
        reason: "备注",
        excluded_by: 1,
        excluded_by_username: "admin",
        excluded_at: 1_782_600_100,
      }))
      .mockResolvedValueOnce(json(GALLERY))      // loadGallery
      .mockResolvedValueOnce(json({ root_id: 10, entries: [
        { id: 56, relative_path: "exports", reason: "备注", excluded_by: 1,
          excluded_by_username: "admin", excluded_at: 1_782_600_100 },
      ]}))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()

    // Open chooser
    await w.findAll("button").find((b) => b.text().includes("添加排除"))!.trigger("click")
    await flushPromises()

    const choosers = w.findAllComponents(DirectoryChooser)
    const chooser = choosers.find((c) => c.props("rootId") === 10)!
    expect(chooser).toBeTruthy()
    expect(chooser.props("startPath")).toBe("/photos/main")
    const browseCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/browse-fs",
    )
    expect(JSON.parse(browseCall![1].body! as string)).toMatchObject({
      path: "/photos/main",
      root_id: 10,
    })

    chooser.vm.$emit("confirm", "/photos/main/exports")
    await flushPromises()

    const postCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) =>
        c[0] === "/api/admin/galleries/1/roots/10/exclusions" && c[1].method === "POST",
    )
    expect(JSON.parse(postCall![1].body! as string)).toEqual({
      absolute_path: "/photos/main/exports",
      reason: "备注",
    })
  })

  it("prompt Cancel aborts the exclusion add — no POST is sent", async () => {
    vi.stubGlobal("prompt", vi.fn().mockReturnValue(null))
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))      // gallery
      .mockResolvedValueOnce(json(EXCLUSIONS))   // exclusions GET (panel open below)
      .mockResolvedValueOnce(json({              // browse-fs when chooser opens
        path: "/photos/main", entries: [], truncated: false,
      }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()

    await w.findAll("button").find((b) => b.text().includes("添加排除"))!.trigger("click")
    await flushPromises()

    const choosers = w.findAllComponents(DirectoryChooser)
    const chooser = choosers.find((c) => c.props("rootId") === 10)!
    expect(chooser).toBeTruthy()
    chooser.vm.$emit("confirm", "/photos/main/exports")
    await flushPromises()

    // Only gallery GET, exclusions GET, and browse-fs POST — no exclusion POST.
    const postCalls = fetchFn.mock.calls.filter(
      (c: [string, RequestInit]) =>
        c[0] === "/api/admin/galleries/1/roots/10/exclusions" && c[1].method === "POST",
    )
    expect(postCalls).toHaveLength(0)
  })

  it("refetches exclusions when reopening a panel stuck on an error", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))                       // gallery
      .mockResolvedValueOnce(json(EXCLUSIONS))                    // exclusions GET
      .mockResolvedValueOnce(new Response(null, { status: 500 })) // DELETE fails
      .mockResolvedValueOnce(json(EXCLUSIONS))                    // GET after reopen
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    const toggleBtn = w.findAll("button").find((b) => b.text() === "排除目录")!
    await toggleBtn.trigger("click")
    await flushPromises()

    await w.findAll("button").find((b) => b.text() === "解除")!.trigger("click")
    await flushPromises()

    // Sticky error replaces the list in the panel.
    expect(w.text()).toMatch(/错误/)
    const exclusionsGets = () => fetchFn.mock.calls.filter(
      (c: [string, RequestInit]) =>
        c[0] === "/api/admin/galleries/1/roots/10/exclusions" && c[1].method === "GET",
    ).length
    expect(exclusionsGets()).toBe(1)

    // Close then reopen: a fresh GET must be attempted despite the cache.
    await toggleBtn.trigger("click")
    await flushPromises()
    await toggleBtn.trigger("click")
    await flushPromises()
    expect(exclusionsGets()).toBe(2)
  })
})
