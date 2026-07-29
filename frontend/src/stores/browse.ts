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
  items: ImageRow[]
  nextCursor: string | null
  scrollY: number
  keyString: string
  atime: number
}

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

  async function load(k: BrowseKey, opts: { force?: boolean } = {}) {
    const key = keyOf(k)
    if (!opts.force && cache.value.has(key)) {
      touch(cache.value.get(key)!)
      return
    }
    const params = new URLSearchParams({ path: k.path, sort: k.sort })
    const r = await apiGet<{ items: ImageRow[]; next_cursor: string | null }>(
      `/api/galleries/${k.gid}/roots/${k.rid}/images?${params}`,
    )
    cache.value.set(key, { items: r.items, nextCursor: r.next_cursor, scrollY: 0, keyString: key, atime: Date.now() })
    evict()
  }

  async function loadMore(k: BrowseKey): Promise<boolean> {
    const entry = get(k)
    if (!entry || !entry.nextCursor) return false
    const params = new URLSearchParams({ path: k.path, sort: k.sort, cursor: entry.nextCursor })
    const r = await apiGet<{ items: ImageRow[]; next_cursor: string | null }>(
      `/api/galleries/${k.gid}/roots/${k.rid}/images?${params}`,
    )
    entry.items.push(...r.items)
    entry.nextCursor = r.next_cursor
    touch(entry)
    return r.items.length > 0
  }

  function saveScroll(k: BrowseKey, y: number) {
    const e = get(k)
    if (e) {
      e.scrollY = y
      touch(e)
    }
  }

  /** 从当前视图（缓存条目）中移除一张图片。批量删除时也可用。 */
  function removeImages(k: BrowseKey, imageIds: number[]) {
    const e = get(k)
    if (!e) return
    const set = new Set(imageIds)
    e.items = e.items.filter((it) => !set.has(it.id))
    touch(e)
  }

  return { cache, get, load, loadMore, saveScroll, removeImages }
})
