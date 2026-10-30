import { describe, expect, it, vi, beforeEach } from "vitest"
import { HttpError, apiGet, apiPost, errorMessage } from "../api"

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

  it("maps a FastAPI-native 422 ({detail}) to a Chinese request_rejected message", async () => {
    // 旧版后端（schema 仍要求 absolute_path）会让 Pydantic 直接回 422，
    // 形状是 {detail:[...]} 而非本应用的 {error:{code,message}} 信封。
    ;(fetch as any).mockResolvedValue(new Response(
      JSON.stringify({
        detail: [{ loc: ["body", "absolute_path"], msg: "Field required", type: "missing" }],
      }),
      { status: 422, headers: { "content-type": "application/json" } },
    ))
    const err = (await apiPost("/api/x", { relative_path: "trip" }).catch((e) => e)) as HttpError
    expect(err).toBeInstanceOf(HttpError)
    expect(err).toMatchObject({ code: "request_rejected", status: 422 })
    expect(err.message).toBe("请求被服务器拒绝（422）")
    expect(errorMessage(err)).toBe("请求被服务器拒绝")
  })

  it("maps an HTML 502 from a reverse proxy to the same Chinese fallback", async () => {
    ;(fetch as any).mockResolvedValue(new Response("<html>Bad Gateway</html>", {
      status: 502,
      headers: { "content-type": "text/html" },
    }))
    const err = (await apiGet("/api/x").catch((e) => e)) as HttpError
    expect(err).toMatchObject({ code: "internal_error", status: 502 })
    expect(err.message).toBe("请求被服务器拒绝（502）")
  })
})
