import { defineConfig, presetUno } from "unocss"

// 名称与 base.css 中的 --color-* 变量一一对应。
const tokenNames = [
  "base", "surface", "surface-2", "surface-3", "surface-4",
  "line", "line-strong",
  "ink", "ink-2", "ink-muted",
  "primary", "primary-hover", "primary-text", "primary-soft",
  "danger", "danger-hover", "danger-text", "danger-soft", "danger-line",
  "success", "success-btn", "success-btn-hover",
  "warning", "warning-soft", "warning-line", "warning-btn", "warning-btn-hover",
  "focus-ring",
] as const

const channel = (name: string) => `rgb(var(--color-${name}) / <alpha-value>)`

export default defineConfig({
  presets: [presetUno()],
  theme: {
    colors: Object.fromEntries(tokenNames.map((n) => [n, channel(n)])),
  },
})
