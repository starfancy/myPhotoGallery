import { describe, expect, it } from "vitest"
import {
  HttpError,
  errorMessage,
  isAccessScopeViolation,
  isUnauthenticated,
} from "../api"

describe("apiClient error helpers (P4)", () => {
  it("errorMessage maps known error codes to zh messages", () => {
    const e = new HttpError(403, "access_scope_violation", "this account is restricted")
    expect(errorMessage(e)).toBe(
      "该账号仅限局域网访问，请连接家庭 Wi-Fi 后重试",
    )
  })

  it("errorMessage maps login_locked to throttled message", () => {
    const e = new HttpError(423, "login_locked", "too many")
    expect(errorMessage(e)).toBe("登录尝试过多，请稍后再试")
  })

  it("errorMessage falls back to err.message for unknown codes", () => {
    const e = new HttpError(400, "wat", "mystery")
    expect(errorMessage(e)).toBe("mystery")
  })

  it("errorMessage accepts an explicit fallback", () => {
    const e = new HttpError(400, "wat", "mystery")
    expect(errorMessage(e, "自定义")).toBe("自定义")
  })

  it("errorMessage handles non-HttpError", () => {
    expect(errorMessage(new Error("x"))).toBe("未知错误")
    expect(errorMessage("string error")).toBe("未知错误")
  })

  it("isAccessScopeViolation matches the lan-only 403", () => {
    expect(
      isAccessScopeViolation(new HttpError(403, "access_scope_violation", "x")),
    ).toBe(true)
    expect(isAccessScopeViolation(new HttpError(403, "forbidden", "x"))).toBe(
      false,
    )
    expect(isAccessScopeViolation(new Error("x"))).toBe(false)
  })

  it("isUnauthenticated matches any 401", () => {
    expect(isUnauthenticated(new HttpError(401, "unauthenticated", "x"))).toBe(
      true,
    )
    expect(isUnauthenticated(new HttpError(401, "invalid_credentials", "x"))).toBe(
      true,
    )
    expect(isUnauthenticated(new HttpError(403, "forbidden", "x"))).toBe(false)
  })
})
