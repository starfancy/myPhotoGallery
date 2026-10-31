<template>
  <form class="flex items-center gap-2 text-sm" @submit.prevent="flush">
    <div class="relative">
      <input
        ref="inputEl"
        type="search"
        :value="text"
        placeholder="搜索文件名或文件夹…"
        aria-label="搜索"
        class="w-44 rounded bg-surface-2 py-1 pl-2 pr-6 text-ink placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-primary"
        @input="onInput"
      >
      <button
        v-if="text"
        type="button"
        aria-label="清除搜索"
        class="absolute right-1 top-1/2 -translate-y-1/2 px-0.5 leading-none text-ink-2 hover:text-ink"
        @click="clear"
      >×</button>
    </div>
    <label
      v-if="!isRoot"
      class="flex shrink-0 select-none items-center gap-1 whitespace-nowrap text-ink-2"
    >
      <input
        type="checkbox"
        class="accent-primary"
        :checked="scopeAll"
        @change="onScopeChange(($event.target as HTMLInputElement).checked)"
      >
      整个 root
    </label>
  </form>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue"

const props = defineProps<{
  modelValue: string
  scopeAll: boolean
  /** 在 root 根目录时为 true：子树本就等于整个 root，隐藏勾选 */
  isRoot: boolean
}>()

const emit = defineEmits<{
  (e: "update:modelValue", v: string): void
  (e: "update:scopeAll", v: boolean): void
}>()

const text = ref(props.modelValue)
const inputEl = ref<HTMLInputElement | null>(null)
let timer: number | null = null

// 路由前进/后退带来的外部 query 变化同步回输入框；输入自身触发的同值更新不重复排防抖
watch(
  () => props.modelValue,
  (v) => {
    if (v !== text.value) text.value = v
  },
)

function schedule() {
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    timer = null
    emit("update:modelValue", text.value)
  }, 300)
}

function flush() {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
  emit("update:modelValue", text.value)
}

function onInput(ev: Event) {
  text.value = (ev.target as HTMLInputElement).value
  schedule()
}

function onScopeChange(v: boolean) {
  emit("update:scopeAll", v)
}

function clear() {
  if (timer !== null) window.clearTimeout(timer)
  timer = null
  text.value = ""
  emit("update:modelValue", "")
  inputEl.value?.focus()
}

onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer)
})
</script>
