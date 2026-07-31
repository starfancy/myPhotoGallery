import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { HttpError, apiGet, apiPost } from "../api"

export interface AuthUser {
  id: number
  username: string
  role: "admin" | "viewer"
  access_scope: "lan_only" | "remote_allowed"
  enabled?: number
  last_login_at?: number | null
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null)
  const loading = ref(false)
  const isAdmin = computed(() => user.value?.role === "admin")
  /** 该账号被允许的访问域（来自 user.access_scope，而非当前请求的源 IP）。 */
  const accessScope = computed(() => user.value?.access_scope ?? null)

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

  return { user, loading, isAdmin, accessScope, fetchMe, login, logout }
})
