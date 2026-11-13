<script setup lang="ts">
/** 拍摄日期范围筛选（tags §4.2）：两个原生 date input，值为 YYYY-MM-DD，
 *  由父组件持久化到 URL query。date 转 epoch 秒在发请求时做。 */
const props = defineProps<{
  dateFrom: string
  dateTo: string
}>()
const emit = defineEmits<{
  (e: "update:dateFrom", v: string): void
  (e: "update:dateTo", v: string): void
}>()

const hasValue = () => props.dateFrom !== "" || props.dateTo !== ""
</script>

<template>
  <div class="flex items-center gap-1 text-sm" role="group" aria-label="拍摄日期筛选">
    <input
      type="date"
      :value="dateFrom"
      class="min-h-11 rounded bg-surface-2 px-2 py-1 text-ink"
      aria-label="起始日期"
      @input="emit('update:dateFrom', ($event.target as HTMLInputElement).value)"
    />
    <span class="text-ink-2">至</span>
    <input
      type="date"
      :value="dateTo"
      class="min-h-11 rounded bg-surface-2 px-2 py-1 text-ink"
      aria-label="结束日期"
      @input="emit('update:dateTo', ($event.target as HTMLInputElement).value)"
    />
    <button
      v-if="hasValue()"
      type="button"
      class="min-h-11 rounded px-1.5 py-1 text-ink-2 hover:text-ink"
      title="清除日期筛选"
      aria-label="清除日期筛选"
      @click="emit('update:dateFrom', ''); emit('update:dateTo', '')"
    >
      ×
    </button>
  </div>
</template>
