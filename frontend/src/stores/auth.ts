import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { HttpError, apiGet, apiPost } from "../api"

export interface AuthUser {
  id: number
  username: string
  role: "admin" | "viewer"
  access_scope: "lan_only" | "remote_allowed"
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null)
  const loading = ref(false)
  const isAdmin = computed(() => user.value?.role === "admin")

  async function fetchMe() {
    loading.value = true
    try {
      user.value = await apiGet<AuthUser>("/api/auth/me")
    } catch (err) {
      if (err instanceof HttpError && err.status === 401) {
        user.value = null
      } else {
        throw err
      }
    } finally {
      loading.value = false
    }
  }

  async function login(username: string, password: string) {
    const r = await apiPost<{ user: AuthUser }>("/api/auth/login", { username, password })
    user.value = r.user
  }

  async function logout() {
    await apiPost<void>("/api/auth/logout")
    user.value = null
  }

  return { user, loading, isAdmin, fetchMe, login, logout }
})
