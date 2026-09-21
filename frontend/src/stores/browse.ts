import { defineStore } from "pinia"
import { ref } from "vue"
import { apiGet } from "../api"

export interface ImageRow {
  id: number
  filename: string
  width: number | null
  height: number | null
  sha1: string
  size_bytes: number
  taken_at: number | null
  is_raw: boolean
}

export interface BrowseKey {
  gid: number
  rid: number
  path: string
  sort: string
}

interface CacheEntry {
  /** 页码（1 起）→ 该页图片行 */
  pages: Map<number, ImageRow[]>
  total: number
  scrollY: number
  keyString: string
  atime: number
}

/** 每页图片数；文件夹图片超过此值时底部分页。 */
export const PAGE_SIZE = 200

const CACHE_MAX = 20

function keyOf(k: BrowseKey) {
  return `${k.gid}|${k.rid}|${k.path}|${k.sort}`
}

export const useBrowseStore = defineStore("browse", () => {
  const cache = ref(new Map<string, CacheEntry>())

  function touch(entry: CacheEntry) {
    entry.atime = Date.now()
  }

  function evict() {
    while (cache.value.size > CACHE_MAX) {
      let oldestKey: string | null = null
      let oldest = Infinity
      for (const [k, v] of cache.value) {
        if (v.atime < oldest) {
          oldest = v.atime
          oldestKey = k
        }
      }
      if (oldestKey) cache.value.delete(oldestKey)
      else break
    }
  }

  function get(k: BrowseKey) {
    return cache.value.get(keyOf(k)) ?? null
  }

  /** 加载指定文件夹的第 page 页（1 起）。已缓存的页不重复请求。 */
  async function loadPage(
    k: BrowseKey,
    page: number,
  ): Promise<{ items: ImageRow[]; total: number }> {
    const key = keyOf(k)
    let entry = cache.value.get(key)
    if (!entry) {
      entry = { pages: new Map(), total: 0, scrollY: 0, keyString: key, atime: Date.now() }
      cache.value.set(key, entry)
      evict()
    }
    const cached = entry.pages.get(page)
    if (cached) {
      touch(entry)
      return { items: cached, total: entry.total }
    }
    const params = new URLSearchParams({
      path: k.path,
      sort: k.sort,
      limit: String(PAGE_SIZE),
      offset: String((page - 1) * PAGE_SIZE),
    })
    const r = await apiGet<{ items: ImageRow[]; total: number }>(
      `/api/galleries/${k.gid}/roots/${k.rid}/images?${params}`,
    )
    entry.pages.set(page, r.items)
    entry.total = r.total
    touch(entry)
    return { items: r.items, total: r.total }
  }

  /** 使某视图的全部缓存页失效（删除图片后调用，避免后续页 offset 漂移）。 */
  function invalidate(k: BrowseKey) {
    cache.value.delete(keyOf(k))
  }

  function saveScroll(k: BrowseKey, y: number) {
    const e = get(k)
    if (e) {
      e.scrollY = y
      touch(e)
    }
  }

  return { cache, get, loadPage, invalidate, saveScroll }
})
