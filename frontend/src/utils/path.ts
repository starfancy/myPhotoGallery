/**
 * 逐段百分号编码相对路径（posix 风格，"/" 分隔）。
 * 用于拼路由 URL：文件夹名含 ?、#、% 等字符时不会破坏路径。
 * 空字符串原样返回。
 */
export function encodePathSegments(rel: string): string {
  return rel.split("/").map(encodeURIComponent).join("/")
}
