/** 后端 group → 中文显示名。未映射的 group 直接显示原文。 */
export const LUT_GROUP_LABELS: Record<string, string> = {
  fujifilm: "富士胶片",
  kodak: "柯达",
  cinematic: "电影感",
  synthetic: "合成预设",
}

export function groupLabel(g: string): string {
  return (LUT_GROUP_LABELS[g] ?? g) || "未分组"
}
