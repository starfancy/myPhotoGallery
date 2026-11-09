// 一次性（可重跑）生成 3 支内置合成 .cube 预设到 ../public/filters/。
// 这是占位资产：真实胶片 LUT 后续人工丢进同目录并在 manifest.json 加行。
import { mkdirSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const outDir = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "filters")
mkdirSync(outDir, { recursive: true })

const N = 33
function toCube(title, fn) {
  const lines = [`# ${title} (built-in synthetic preset)`, `LUT_3D_SIZE ${N}`]
  for (let b = 0; b < N; b++)
    for (let g = 0; g < N; g++)
      for (let r = 0; r < N; r++) {
        const [R, G, B] = fn(r / (N - 1), g / (N - 1), b / (N - 1))
        lines.push([R, G, B].map((v) => v.toFixed(6)).join(" "))
      }
  return lines.join("\n") + "\n"
}

const presets = {
  "warm.cube": toCube("warm", (r, g, b) => [
    Math.min(1, r * 1.08 + 0.02),
    Math.min(1, g * 1.0 + 0.0),
    Math.max(0, b * 0.88 - 0.02),
  ]),
  "cool.cube": toCube("cool", (r, g, b) => [
    Math.max(0, r * 0.88 - 0.02),
    Math.min(1, g * 1.0 + 0.0),
    Math.min(1, b * 1.08 + 0.02),
  ]),
  "mono.cube": toCube("mono", (r, g, b) => {
    const y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return [y, y, y]
  }),
}

for (const [file, content] of Object.entries(presets)) {
  writeFileSync(join(outDir, file), content)
  console.log("wrote", file)
}
