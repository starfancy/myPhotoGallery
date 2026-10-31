/**
 * 审计 action 英文键 → 中文界面标签的唯一事实来源。
 * 全集以后端 write_audit(...) 调用点为准；tests/audit-labels.spec.ts 守全集。
 */
export const AUDIT_ACTION_LABELS = {
  login_success: "登录成功",
  login_fail: "登录失败",
  user_create: "创建用户",
  user_delete: "删除用户",
  user_update: "更新用户",
  user_disable: "禁用用户",
  user_enable: "启用用户",
  user_reset_password: "重置密码",
  gallery_create: "创建图库",
  gallery_update: "更新图库",
  gallery_delete: "删除图库",
  root_add: "添加根目录",
  root_update: "更新根目录",
  root_remove: "移除根目录",
  exclusion_add: "新增排除",
  exclusion_remove: "解除排除",
  image_delete: "删除图片",
  image_restore: "恢复图片",
  trash_purge: "清理回收站",
  thumb_cache_purge: "清理缩略图缓存",
  scan_start: "开始扫描",
  scan_finish: "完成扫描",
  scan_error: "扫描失败",
  rescan_exif: "重扫 EXIF",
  fs_browse: "浏览目录",
  settings_update: "更新设置",
} as const satisfies Record<string, string>

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action as keyof typeof AUDIT_ACTION_LABELS] ?? action
}
