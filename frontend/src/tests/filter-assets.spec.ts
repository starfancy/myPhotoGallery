import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { parseCube } from "../lib/lutParser"

const FILTERS_DIR = join(__dirname, "../../public/filters")

describe("filter assets", () => {
  const manifest = JSON.parse(
    readFileSync(join(FILTERS_DIR, "manifest.json"), "utf-8"),
  )

  it("manifest has at least 3 presets with unique ids", () => {
    expect(manifest.length).toBeGreaterThanOrEqual(3)
    const ids = manifest.map((f: any) => f.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it("every manifest entry points to a parseable .cube file", () => {
    for (const f of manifest) {
      const text = readFileSync(join(FILTERS_DIR, f.file), "utf-8")
      const lut = parseCube(text)
      expect(lut.size).toBe(33)
      expect(lut.data.length).toBe(33 ** 3 * 3)
    }
  })

  it("LICENSE.md documents the synthetic-preset provenance", () => {
    const lic = readFileSync(join(FILTERS_DIR, "LICENSE.md"), "utf-8")
    expect(lic).toMatch(/synthetic|built-in/i)
  })
})
