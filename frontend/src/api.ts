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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "include",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
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
    const code = data?.error?.code ?? "internal_error"
    const msg = data?.error?.message ?? res.statusText
    throw new HttpError(res.status, code, msg)
  }
  return data as T
}

export const apiGet = <T>(p: string) => request<T>("GET", p)
export const apiPost = <T>(p: string, body?: unknown) => request<T>("POST", p, body ?? {})
export const apiDelete = <T>(p: string) => request<T>("DELETE", p)
