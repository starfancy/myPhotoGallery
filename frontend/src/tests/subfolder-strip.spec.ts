import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import SubfolderStrip from "../components/SubfolderStrip.vue"

interface FolderCard {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
  cover_source_name?: string | null
}

// VTU 的默认 RouterLink stub 不渲染插槽（卡片内容会整体消失），
// 故用一个透传默认插槽的 a 标签占位。
const RouterLinkSlotStub = { template: "<a><slot /></a>" }

function mountWith(folders: FolderCard[]) {
  return mount(SubfolderStrip, {
    props: { folders, gid: 1, rid: 1 },
    global: { stubs: { RouterLink: RouterLinkSlotStub } },
  })
}

describe("SubfolderStrip borrowed-cover label", () => {
  it("renders the source child name as a bottom gradient label", () => {
    const w = mountWith([
      {
        name: "2024旅行",
        relative_path: "trip",
        image_count: 0,
        descendant_count: 128,
        cover_thumb_sha1: "sha-gz",
        cover_source_name: "广州",
      },
    ])
    const label = w.find(".lb-folder-source")
    expect(label.exists()).toBe(true)
    expect(label.text()).toContain("广州")
    expect(label.attributes("title")).toBe("广州")
  })

  it("renders no label for normal folders without cover_source_name", () => {
    const w = mountWith([
      {
        name: "日常",
        relative_path: "daily",
        image_count: 12,
        descendant_count: 12,
        cover_thumb_sha1: "sha-daily",
      },
    ])
    expect(w.find(".lb-folder-source").exists()).toBe(false)
  })

  it("renders no label when cover_source_name is null", () => {
    const w = mountWith([
      {
        name: "真空",
        relative_path: "nope",
        image_count: 0,
        descendant_count: 0,
        cover_thumb_sha1: null,
        cover_source_name: null,
      },
    ])
    expect(w.find(".lb-folder-source").exists()).toBe(false)
  })
})
