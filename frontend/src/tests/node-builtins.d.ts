// 为什么有这个文件：theme-guard.spec.ts 用 node:fs/path + __dirname 扫描源码，
// vitest 运行时由 Node 提供这些能力，但本仓库未安装 @types/node（P7 约束：不引新依赖），
// 这里只给守卫测试用到的几个 API 补最小环境声明，让 vue-tsc（pnpm build）通过。
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf-8"): string
  export function readdirSync(path: string): string[]
  export function statSync(path: string): { isDirectory(): boolean }
}

declare module "node:path" {
  export function join(...parts: string[]): string
}

declare const __dirname: string
