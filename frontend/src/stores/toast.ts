import { defineStore } from "pinia"
import { ref } from "vue"

export const useToastStore = defineStore("toast", () => {
  const items = ref<Array<{ id: number; kind: "info" | "error"; text: string }>>([])
  let nextId = 1
  function push(kind: "info" | "error", text: string) {
    const id = nextId++
    items.value.push({ id, kind, text })
    setTimeout(() => {
      items.value = items.value.filter((x) => x.id !== id)
    }, 4000)
  }
  return { items, push }
})
