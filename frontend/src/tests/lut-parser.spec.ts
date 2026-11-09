import { describe, expect, it } from "vitest"
import { parseCube } from "../lib/lutParser"

const SAMPLE = `
# comment line
TITLE "tiny"
LUT_3D_SIZE 2
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0
0.0 0.0 0.0
1.0 0.0 0.0
0.0 1.0 0.0
1.0 1.0 0.0
0.0 0.0 1.0
1.0 0.0 1.0
0.0 1.0 1.0
1.0 1.0 1.0
`

describe("parseCube", () => {
  it("parses size and RGB triples in .cube row order", () => {
    const lut = parseCube(SAMPLE)
    expect(lut.size).toBe(2)
    expect(lut.data.length).toBe(2 * 2 * 2 * 3)
    // 第一行 "0 0 0"
    expect(lut.data[0]).toBe(0)
    expect(lut.data[1]).toBe(0)
    expect(lut.data[2]).toBe(0)
    // 第二行 "1 0 0" → 255
    expect(lut.data[3]).toBe(255)
    expect(lut.data[4]).toBe(0)
    expect(lut.data[5]).toBe(0)
  })

  it("clamps out-of-range floats into 0..255", () => {
    const lut = parseCube(`LUT_3D_SIZE 1\n-0.5 2.0 0.5`)
    expect(lut.data[0]).toBe(0)
    expect(lut.data[1]).toBe(255)
    expect(lut.data[2]).toBe(Math.round(0.5 * 255))
  })

  it("throws when LUT_3D_SIZE missing", () => {
    expect(() => parseCube("0.0 0.0 0.0")).toThrow(/LUT_3D_SIZE/)
  })

  it("throws when triple count mismatches size^3", () => {
    expect(() => parseCube("LUT_3D_SIZE 2\n0.0 0.0 0.0")).toThrow(/expected 24, got 3/)
  })

  it("skips blank lines and non-header text rows without 3 numeric parts", () => {
    const lut = parseCube(`LUT_3D_SIZE 1\n\nnot a row\n0.1 0.2 0.3`)
    expect(lut.size).toBe(1)
    expect(lut.data.length).toBe(3)
  })
})
