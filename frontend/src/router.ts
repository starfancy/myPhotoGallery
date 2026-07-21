import { createRouter, createWebHistory, RouteRecordRaw } from "vue-router"

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/galleries" },
  { path: "/login", component: () => import("./views/LoginView.vue") },
  { path: "/galleries", component: () => import("./views/GalleryListView.vue") },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
