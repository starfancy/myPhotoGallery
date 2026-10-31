import { AUDIT_ACTION_LABELS, auditActionLabel } from "../utils/audit"

// 以后端 write_audit(...) 实际调用点为准的全集；后端新增事件时此处会逼出评审。
const BACKEND_ACTIONS = [
  "login_success", "login_fail",
  "user_create", "user_delete", "user_update", "user_disable", "user_enable",
  "user_reset_password",
  "gallery_create", "gallery_update", "gallery_delete",
  "root_add", "root_update", "root_remove",
  "exclusion_add", "exclusion_remove",
  "image_delete", "image_restore", "trash_purge",
  "thumb_cache_purge",
  "scan_start", "scan_finish", "scan_error", "rescan_exif",
  "fs_browse", "settings_update",
]

describe("audit action labels", () => {
  it("covers every backend action exactly once", () => {
    expect(Object.keys(AUDIT_ACTION_LABELS).sort()).toEqual([...BACKEND_ACTIONS].sort())
  })
  it("maps known actions to Chinese and falls back to raw value", () => {
    expect(auditActionLabel("image_delete")).toBe("删除图片")
    expect(auditActionLabel("some_future_action")).toBe("some_future_action")
  })
})
