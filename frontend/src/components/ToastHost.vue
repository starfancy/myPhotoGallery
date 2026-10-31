<template>
  <div aria-live="polite" aria-atomic="false"
       class="pointer-events-none fixed inset-x-0 bottom-4 z-[80] flex flex-col items-center gap-2 px-4">
    <div v-for="t in toast.items" :key="t.id"
         class="pointer-events-auto rounded-md px-4 py-2 text-sm shadow-lg"
         :class="t.kind === 'error'
           ? 'bg-danger-soft text-danger-text border border-danger-line/60'
           : 'bg-surface-2 text-ink border border-line'">
      {{ t.text }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { useToastStore } from "../stores/toast"
const toast = useToastStore()
</script>
