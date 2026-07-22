<template>
  <div>
    <AppHeader>
      <template #title>
        <span class="text-neutral-400">编辑图库 #{{ gid }}</span>
      </template>
    </AppHeader>
    <main class="p-4">
      <!-- Full editor lands in P2-11. Stub keeps the route resolvable. -->
      <div class="text-neutral-400">图库编辑（占位）</div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useRoute } from "vue-router"
import AppHeader from "../components/AppHeader.vue"

const route = useRoute()
// vue-router types route.params.gid as string | string[]; single-segment
// param always yields string, but coerce defensively for P2-11 consumers.
const gid = computed(() => String(route.params.gid))
</script>
