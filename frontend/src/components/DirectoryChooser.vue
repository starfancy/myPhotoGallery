<template>
  <div v-if="modelValue"
       class="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
       @click.self="cancel">
    <div class="w-full max-w-2xl overflow-hidden rounded-lg bg-neutral-900 shadow-xl"
         role="dialog" aria-modal="true" @keydown.esc="cancel" tabindex="-1" ref="dialogEl">
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-neutral-800 px-4 py-3">
        <div class="font-medium">选择目录</div>
        <button class="rounded px-2 py-1 text-sm text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                @click="cancel" aria-label="关闭">✕</button>
      </div>

      <!-- Breadcrumbs -->
      <div class="flex flex-wrap items-center gap-1 border-b border-neutral-800 px-4 py-2 text-xs">
        <button class="rounded px-1.5 py-0.5 hover:bg-neutral-800"
                @click="navigateTo('')">根</button>
        <template v-for="(bc, i) in breadcrumbs" :key="i">
          <span class="text-neutral-600">/</span>
          <button class="rounded px-1.5 py-0.5 hover:bg-neutral-800"
                  @click="navigateTo(bc.path)">{{ bc.name }}</button>
        </template>
      </div>

      <!-- Manual path input -->
      <div class="border-b border-neutral-800 px-4 py-2">
        <input v-model="manualPath" @keydown.enter.prevent="navigateTo(manualPath)"
               placeholder="输入路径后按 Enter"
               class="w-full rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 placeholder:text-neutral-500 focus:outline-none focus:ring-1 focus:ring-blue-500" />
      </div>

      <!-- Directory list -->
      <div class="max-h-96 overflow-y-auto">
        <div v-if="loading" class="p-4 text-sm text-neutral-400">加载中...</div>
        <div v-else-if="error" class="p-4 text-sm text-red-400">{{ error }}</div>
        <template v-else>
          <div v-if="truncated"
               class="border-b border-yellow-900/40 bg-yellow-900/20 px-4 py-2 text-xs text-yellow-300">
            该目录条目过多，仅显示前 5000 项
          </div>
          <ul v-if="entries.length > 0" class="divide-y divide-neutral-800">
            <li v-for="e in entries" :key="e.path">
              <button class="flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-neutral-800"
                      @dblclick="navigateTo(e.path)"
                      @click="selectEntry(e)"
                      :class="{ 'bg-neutral-800': selected === e.path }">
                <span aria-hidden="true">{{ e.is_root ? "💽" : "📁" }}</span>
                <span class="truncate">{{ e.name }}</span>
              </button>
            </li>
          </ul>
          <div v-else class="p-4 text-sm text-neutral-500">
            {{ currentPath ? "此目录下没有子目录" : "无可用位置" }}
          </div>
        </template>
      </div>

      <!-- Footer -->
      <div class="flex items-center justify-between gap-3 border-t border-neutral-800 px-4 py-3">
        <div class="min-w-0 flex-1 truncate text-xs text-neutral-500" :title="confirmTarget || '未选择'">
          将选择: <span class="text-neutral-300">{{ confirmTarget || "未选择" }}</span>
        </div>
        <div class="flex gap-2">
          <button class="rounded px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
                  @click="cancel">取消</button>
          <button class="rounded bg-blue-600 px-3 py-1.5 text-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="!confirmTarget"
                  @click="confirmSelection">确认</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue"
import { apiPost, HttpError } from "../api"

interface Props {
  modelValue: boolean
  startPath?: string
}

const props = withDefaults(defineProps<Props>(), {
  startPath: "",
})

const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void
  (e: "confirm", path: string): void
}>()

interface DirEntry {
  name: string
  path: string
  is_root: boolean
}

interface BrowseResponse {
  path: string
  entries: DirEntry[]
  truncated: boolean
}

const currentPath = ref<string>("")
const entries = ref<DirEntry[]>([])
const truncated = ref(false)
const loading = ref(false)
const error = ref("")
const selected = ref<string>("")
const manualPath = ref<string>("")
const dialogEl = ref<HTMLElement | null>(null)

// The path the user actually confirms: prefer an explicit selection from the
// entry list; if nothing is selected but the user is inside a real directory,
// confirm the current directory. Windows drive-root (path === "") is never
// confirmable because it isn't a real filesystem path.
const confirmTarget = computed(() => selected.value || currentPath.value || "")

// Split an absolute path into breadcrumb segments. Handles both POSIX ("/a/b")
// and Windows ("C:\\a\\b" or "C:/a/b") forms; the reconstructed path uses the
// same separator the server used, so it round-trips through the API cleanly.
const breadcrumbs = computed(() => {
  const p = currentPath.value
  if (!p) return []
  // Prefer backslash whenever the path looks Windows-shaped ("C:..."), even
  // if the current string has no backslash yet — this covers bare "C:"
  // typed into the manual input before the server has round-tripped it.
  const isWinShape = /^[A-Za-z]:/.test(p)
  const sep = p.includes("\\") || isWinShape ? "\\" : "/"
  const isWinDrive = /^[A-Za-z]:[\\/]$/.test(p) || /^[A-Za-z]:$/.test(p)
  const parts = p.split(/[\\/]+/).filter(Boolean)
  const out: { name: string; path: string }[] = []
  if (isWinDrive || /^[A-Za-z]:$/.test(parts[0] ?? "")) {
    // Windows: first segment "C:" becomes root "C:\"
    out.push({ name: parts[0], path: parts[0] + sep })
    for (let i = 1; i < parts.length; i++) {
      out.push({
        name: parts[i],
        path: parts[0] + sep + parts.slice(1, i + 1).join(sep),
      })
    }
  } else {
    // POSIX: "/a/b" -> ["a" at /a, "b" at /a/b]
    for (let i = 0; i < parts.length; i++) {
      out.push({
        name: parts[i],
        path: "/" + parts.slice(0, i + 1).join("/"),
      })
    }
  }
  return out
})

async function browse(path: string) {
  loading.value = true
  error.value = ""
  try {
    const data = await apiPost<BrowseResponse>("/api/admin/browse-fs", { path })
    currentPath.value = data.path
    entries.value = data.entries
    truncated.value = data.truncated
    selected.value = ""
    manualPath.value = data.path
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
    entries.value = []
    truncated.value = false
  } finally {
    loading.value = false
  }
}

function navigateTo(path: string) {
  browse(path)
}

function selectEntry(entry: DirEntry) {
  // Drive-root entries (is_root=true, e.g. "C:\\") aren't confirmable
  // targets — only navigable. Ignore single-click selection on them so
  // the user must double-click to descend into an actual folder.
  if (entry.is_root) return
  selected.value = entry.path
}

function confirmSelection() {
  if (!confirmTarget.value) return
  emit("confirm", confirmTarget.value)
  emit("update:modelValue", false)
}

function cancel() {
  emit("update:modelValue", false)
}

// Open lifecycle: whenever the modal is (or becomes) open, load the current
// startPath. `immediate: true` covers the case where the parent mounts us
// with modelValue already true; the plain watcher covers subsequent
// close -> open transitions so a reopened chooser starts fresh.
watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      selected.value = ""
      error.value = ""
      await browse(props.startPath ?? "")
      // Move focus into the dialog so Esc-to-close works immediately.
      await nextTick()
      dialogEl.value?.focus()
    }
  },
  { immediate: true },
)
</script>
