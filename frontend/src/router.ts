import {
  createRouter,
  createWebHistory,
  RouteRecordRaw,
  type RouteLocationNormalized,
} from "vue-router"
import { useAuthStore } from "./stores/auth"

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/galleries" },
  { path: "/login", component: () => import("./views/LoginView.vue"), meta: { public: true } },
  { path: "/galleries", component: () => import("./views/GalleryListView.vue") },
  { path: "/galleries/:gid", component: () => import("./views/RootListView.vue") },
  { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: () => import("./views/BrowseView.vue") },
  { path: "/galleries/:gid/r/:rid/:path(.*)*", component: () => import("./views/BrowseView.vue") },
  {
    path: "/admin",
    component: () => import("./views/AdminOverview.vue"),
    meta: { requiresAdmin: true },
  },
  {
    path: "/admin/galleries",
    component: () => import("./views/AdminGalleryList.vue"),
    meta: { requiresAdmin: true },
  },
  {
    path: "/admin/galleries/:gid",
    component: () => import("./views/AdminGalleryEdit.vue"),
    meta: { requiresAdmin: true },
  },
  {
    path: "/settings/password",
    component: () => import("./views/ChangePasswordView.vue"),
  },
]

/**
 * Route guard: enforces auth + role requirements. Exported for tests so the
 * single source of truth is verified directly rather than duplicated in specs.
 *
 * @param to     target route
 * @param auth   auth store (already instantiated — tests can seed it)
 */
export async function authGuard(
  to: RouteLocationNormalized,
  auth: ReturnType<typeof useAuthStore>,
) {
  if (to.meta.public) return true
  if (auth.user === null && !auth.loading) {
    await auth.fetchMe()
  }
  if (auth.user === null) {
    return { path: "/login", query: { next: to.fullPath } }
  }
  if (to.meta.requiresAdmin && auth.user.role !== "admin") {
    return { path: "/galleries" }
  }
  return true
}

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => authGuard(to, useAuthStore()))
