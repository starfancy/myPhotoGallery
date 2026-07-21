import { describe, expect, it, vi, beforeEach } from "vitest"
import { HttpError, apiGet, apiPost } from "../api"

describe("apiClient", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn())
  })

  it("returns parsed JSON on success", async () => {
    ;(fetch as any).mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }))
    const r = await apiGet<{ ok: number }>("/api/x")
    expect(r).toEqual({ ok: 1 })
    expect((fetch as any).mock.calls[0][1].credentials).toBe("include")
  })

  it("throws HttpError with code on 4xx envelope", async () => {
    ;(fetch as any).mockResolvedValue(new Response(
      JSON.stringify({ error: { code: "invalid_credentials", message: "wrong" } }),
      { status: 401, headers: { "content-type": "application/json" } },
    ))
    await expect(apiPost("/api/auth/login", {})).rejects.toMatchObject({
      code: "invalid_credentials",
      status: 401,
    })
  })

  it("throws HttpError with internal_error on non-JSON 5xx", async () => {
    ;(fetch as any).mockResolvedValue(new Response("boom", { status: 500 }))
    await expect(apiGet("/api/x")).rejects.toMatchObject({ code: "internal_error", status: 500 })
  })
})
