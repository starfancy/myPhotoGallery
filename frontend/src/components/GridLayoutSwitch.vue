<template>
  <div class="flex items-center gap-0.5 rounded bg-surface-2 p-0.5"
       role="group"
       aria-label="缩略图排版方式">
    <button v-for="opt in OPTIONS" :key="opt.value"
            type="button"
            class="flex items-center rounded px-1.5 py-1"
            :class="modelValue === opt.value
                    ? 'bg-surface-3 text-ink'
                    : 'text-ink-2 hover:text-ink'"
            :title="opt.label"
            :aria-label="opt.label"
            :aria-pressed="modelValue === opt.value"
            @click="$emit('update:modelValue', opt.value)">
      <!-- 按行对齐：每行等高、行内宽度随宽高比变化 -->
      <svg v-if="opt.value === 'justified'" width="16" height="16"
           viewBox="0 0 16 16" fill="none" stroke="currentColor"
           stroke-width="1.2" aria-hidden="true">
        <rect x="1" y="1.5" width="6" height="3" />
        <rect x="7.5" y="1.5" width="7.5" height="3" />
        <rect x="1" y="6.5" width="9" height="3" />
        <rect x="10.5" y="6.5" width="4.5" height="3" />
        <rect x="1" y="11.5" width="4.5" height="3" />
        <rect x="6" y="11.5" width="5" height="3" />
        <rect x="11.5" y="11.5" width="3.5" height="3" />
      </svg>
      <!-- 竖版流式：列等宽、高度错落 -->
      <svg v-else width="16" height="16"
           viewBox="0 0 16 16" fill="none" stroke="currentColor"
           stroke-width="1.2" aria-hidden="true">
        <rect x="1" y="1.5" width="3" height="6" />
        <rect x="4.5" y="1.5" width="3" height="10" />
        <rect x="8" y="1.5" width="3" height="4.5" />
        <rect x="11.5" y="1.5" width="3" height="8" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
export type GridLayout = "justified" | "masonry"

defineProps<{ modelValue: GridLayout }>()
defineEmits<{
  (e: "update:modelValue", value: GridLayout): void
}>()

const OPTIONS: { value: GridLayout; label: string }[] = [
  { value: "justified", label: "按行对齐" },
  { value: "masonry", label: "竖版流式" },
]
</script>
