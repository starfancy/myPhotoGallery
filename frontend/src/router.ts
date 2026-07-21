import { createRouter, createWebHistory, RouteRecordRaw } from "vue-router"
import { useAuthStore } from "./stores/auth"

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/galleries" },
  { path: "/login", component: () => import("./views/LoginView.vue"), meta: { public: true } },
  { path: "/galleries", component: () => import("./views/GalleryListView.vue") },
  { path: "/galleries/:gid", component: () => import("./views/RootListView.vue") },
  { path: "/galleries/:gid/r/:rid/:path(.*)*", component: () => import("./views/BrowseView.vue") },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuthStore()
  if (auth.user === null && !auth.loading) {
    await auth.fetchMe()
  }
  if (auth.user === null) {
    return { path: "/login", query: { next: to.fullPath } }
  }
  return true
})
