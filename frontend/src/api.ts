export interface ApiError {
  code: string
  message: string
}

export class HttpError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** P4: 已知错误码 → 用户文案。
 *
 * 仅在调用方明确希望展示"人类可读"消息时使用。
 * 不消费 err.message，避免把后端的英文原文直接呈现给最终用户。
 */
const ERROR_MSG_ZH: Record<string, string> = {
  invalid_credentials: "用户名或密码错误",
  login_locked: "登录尝试过多，请稍后再试",
  access_scope_violation: "该账号仅限局域网访问，请连接家庭 Wi-Fi 后重试",
  admin_fs_lan_only: "该管理功能仅限局域网访问",
  last_admin_protected: "不能删除或禁用最后一个管理员",
  network_error: "网络错误，请检查连接",
  unauthenticated: "请先登录",
  forbidden: "无权访问",
  not_found: "未找到",
  conflict: "已存在",
  request_rejected: "请求被服务器拒绝",
  bad_request: "请求参数无效",
  batch_too_large: "超出批量下载数量上限",
  path_invalid: "路径无效",
  path_not_readable: "路径不可读",
  internal_error: "服务器内部错误",
}

export function errorMessage(err: unknown, fallback?: string): string {
  if (err instanceof HttpError) {
    return ERROR_MSG_ZH[err.code] ?? fallback ?? err.message
  }
  return fallback ?? "未知错误"
}

/** P4: 是否 lan_only 用户被拒绝（用于 banner/引导文案）。 */
export function isAccessScopeViolation(err: unknown): boolean {
  return err instanceof HttpError && err.code === "access_scope_violation"
}

/** P4: 是否"未认证"——由调用方决定是否跳登录。 */
export function isUnauthenticated(err: unknown): boolean {
  return err instanceof HttpError && err.status === 401
}

async function request<T>(
  method: string, path: string, body?: unknown, signal?: AbortSignal,
): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "include",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  }
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (err) {
    throw new HttpError(0, "network_error", (err as Error).message)
  }
  if (res.status === 204) return undefined as unknown as T
  const ct = res.headers.get("content-type") || ""
  const data = ct.includes("application/json") ? await res.json().catch(() => null) : null
  if (!res.ok) {
    if (data?.error) {
      // 本应用统一错误信封 {error:{code,message}}
      throw new HttpError(
        res.status,
        data.error.code ?? "internal_error",
        data.error.message ?? res.statusText,
      )
    }
    // 非应用信封响应：FastAPI/Pydantic 原生 422（{detail:[...]}，如旧版
    // 后端未重启）或反代返回的 HTML 错误页。不透传英文 statusText，统一
    // 给中文兜底并带状态码，便于用户报告问题。
    const code = res.status >= 500 ? "internal_error" : "request_rejected"
    throw new HttpError(res.status, code, `请求被服务器拒绝（${res.status}）`)
  }
  return data as T
}

export const apiGet = <T>(p: string, signal?: AbortSignal) =>
  request<T>("GET", p, undefined, signal)
export const apiPost = <T>(p: string, body?: unknown) => request<T>("POST", p, body ?? {})
export const apiPatch = <T>(p: string, body?: unknown) => request<T>("PATCH", p, body ?? {})
export const apiDelete = <T>(p: string) => request<T>("DELETE", p)
