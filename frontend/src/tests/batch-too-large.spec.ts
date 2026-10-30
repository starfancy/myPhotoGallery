import { describe, expect, it } from "vitest"
import { HttpError, errorMessage } from "../api"

describe("batch_too_large 错误码", () => {
  it("映射为中文文案", () => {
    const msg = errorMessage(new HttpError(400, "batch_too_large", "english raw"))
    expect(msg).toBe("超出批量下载数量上限")
  })
})
