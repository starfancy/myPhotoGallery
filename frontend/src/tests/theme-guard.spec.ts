import { describe, it, expect } from "vitest"
import { readFileSync, readdirSync, statSync } from "node:fs"
import { join } from "node:path"

// 禁止回潮：应用代码不得再出现 Tailwind 色阶硬编码类。
// 豁免：测试目录（断言旧类名时可能引用）、styles/base.css（令牌定义本体）、
// ImageLightbox.vue（灯箱常暗，刻意保留字面量，详见 base.css 注释）。
const SRC = join(__dirname, "..")
const HARDCODED = /(bg|text|border|ring|divide|from|to|outline|placeholder|accent)-(neutral|blue|red|green|yellow|amber|orange|purple)-[0-9]/
const SKIP = new Set(["tests", "styles"])
const SKIP_FILES = new Set(["ImageLightbox.vue"])

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(vue|ts)$/.test(name) && !SKIP_FILES.has(name)) out.push(p)
  }
  return out
}

describe("theme token guard", () => {
  it("no hardcoded Tailwind color-scale classes outside exemptions", () => {
    const offenders: string[] = []
    for (const file of walk(SRC)) {
      const lines = readFileSync(file, "utf-8").split("\n")
      lines.forEach((line, i) => {
        if (HARDCODED.test(line)) offenders.push(`${file}:${i + 1}: ${line.trim()}`)
      })
    }
    expect(offenders).toEqual([])
  })
})
