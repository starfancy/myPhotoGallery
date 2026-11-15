# 人物页左侧簇列表独立滚动 — 设计

日期：2026-11-15
状态：已批准（方案 A：sticky 吸顶 + 自身 max-height 滚动）

## 背景与问题

人物页 [PersonClusterView.vue](../../../frontend/src/views/PersonClusterView.vue)
为左右两栏布局：左侧 `<aside class="w-56 shrink-0 space-y-1">` 渲染全部人物簇
（头像 + 名称 + 照片数），右侧为选中簇的照片按年/月分组。

左侧簇列表没有任何高度约束，簇数量很多时整页被撑高，只能靠浏览器页面滚动条
滚动，左侧列表与右侧照片区共用同一个滚动上下文。用户希望左侧簇列表拥有自己的
垂直滚动条，且在浏览右侧长照片列表时簇列表保持可见、可用。

## 目标

- 左侧簇列表内容超出可视高度时，在 `aside` 内部出现独立垂直滚动条，
  不再撑开整页。
- 滚动右侧照片区时，左侧栏吸顶停留在头部下方，始终可见。
- 簇数量少、不超高时不出现滚动条，页面与现状视觉一致。

## 非目标（明确不做）

- 不改变右侧照片区现有的页面滚动方式。
- 不改动任何组件逻辑、接口、数据结构。
- 不引入自定义滚动条样式库或虚拟滚动；使用浏览器原生滚动条。
- 不调整簇列表项（按钮、头像、名称、计数）的排版与交互。

## 现有机制（复用点）

- [AdminAudit.vue:9](../../../frontend/src/views/AdminAudit.vue#L9)
  已建立吸顶偏移约定：`sticky top-[69px] md:top-[53px]`
  （移动端头部高 69px、桌面端 53px），本设计直接复用这两个基准值。
- 项目内滚动区域统一使用 `max-h-* + overflow-y-auto` 的原生滚动写法
  （[DirectoryChooser.vue:34](../../../frontend/src/components/DirectoryChooser.vue#L34)、
  [AdminUsers.vue:161](../../../frontend/src/views/AdminUsers.vue#L161)）。
- `#main-content` 自带 `p-3`（12px）内边距，吸顶偏移与底部留白以此为基准。

## 设计

仅改动 [PersonClusterView.vue](../../../frontend/src/views/PersonClusterView.vue)
中左侧 `<aside>` 一个元素的 class，由：

```html
<aside class="w-56 shrink-0 space-y-1">
```

改为：

```html
<aside
  class="w-56 shrink-0 space-y-1 overflow-y-auto
         sticky top-[81px] md:top-[65px]
         max-h-[calc(100vh-93px)] md:max-h-[calc(100vh-77px)]"
>
```

各项职责：

1. **`overflow-y-auto`**：内容超出 max-height 时出现原生垂直滚动条；
   不超出时无滚动条。
2. **`sticky top-[81px] md:top-[65px]`**：吸顶偏移 = 头部高度
   （69/53px）+ main 上内边距 12px = 81/65px。右侧照片区很长、页面滚动时
   左栏停在头部正下方，不被 sticky 头部遮挡，也无位移跳动。
3. **`max-h-[calc(100vh-93px)] md:max-h-[calc(100vh-77px)]`**：
   最大高度 = 100vh − 吸顶偏移 − 12px 底部呼吸空间
   （移动 81+12=93px，桌面 65+12=77px），滚动条底端不贴死视口边缘。

sticky 的滚动容器是页面视口（与 AdminAudit 同一模式）；flex 父容器在右侧内容
更高时为 sticky 提供移动空间，右侧内容短、本页无需滚动时布局与现状完全一致。

## 边界与行为

| 情况 | 行为 |
|---|---|
| 簇数量少，列表高度 ≤ max-height | 无滚动条，与现状一致 |
| 簇数量多，列表超高 | aside 内部独立垂直滚动，页面不被左栏撑高 |
| 右侧照片区很长，页面滚动 | 左栏吸顶固定在头部下方，始终可点选 |
| 重命名后 `loadClusters()` 重渲染 | 纯 class 改动，不影响数据流与选中态 |
| 空状态 / 错误态（v-if 另外两个分支） | 不渲染该 aside，零影响 |

## 测试

- 纯 CSS class 改动，jsdom 不做真实布局、无法断言滚动条出现，不新增 vitest 用例；
  人物页当前亦无组件测试。
- 验证手段：`vue-tsc` 类型检查 + 前端构建通过；现有 vitest 套件保持全绿；
  浏览器中以足够多簇的真实库手动确认三种情况（少簇无条、多簇独立滚动、
  右栏滚动时左栏吸顶），并检查浅/深两套主题。

## YAGNI 记录

曾评估的另一个方案：

- **方案 B（整页改为双栏独立滚动，body 不滚动）**：根容器 `h-screen flex-col`、
  main `min-h-0 flex-1`，左右两栏各自 `overflow-y-auto`。更"应用化"，但会改变
  右侧照片区现有滚动方式，并需调整空状态/错误态布局，改动面与回归风险都更大，
  对"左侧加单独滚动条"这一诉求属于过度设计，排除。
