# 灯箱路径胶囊与角落胶囊垂直对齐 — 设计

日期：2026-11-15
状态：已批准

## 背景与问题

[2026-11-15-people-path-toggle-lightbox-bottom-design](2026-11-15-people-path-toggle-lightbox-bottom-design.md)
把灯箱路径标注移到底部居中时，为避开左下角拍摄时间胶囊与右下角缩放比例胶囊，
把 `.pswp__location-label` 固定在 `bottom: 44px`（比两个贴底胶囊高一档）。

实际桌面端使用中，三个胶囊水平方向并不冲突（路径居中、角落胶囊贴边），
悬空一档反而视觉不齐。用户要求路径胶囊与拍摄日期、显示比例对齐到同一垂直高度。

## 目标

- 桌面端（≥768px，与项目 UnoCSS `md` 断点一致）路径胶囊下移到 `bottom: 10px`，
  与两个角落胶囊同一基线；三者本就同规格（`padding: 2px 8px`、`line-height: 20px`、
  13px 字号、同款黑底半透明胶囊），下移后精确齐平。
- 窄屏（<768px）维持 `bottom: 44px` 抬高显示，避免三胶囊在手机宽度挤在同一行
  造成重叠、路径被压到过短。

## 非目标（明确不做）

- 不改拍摄时间、缩放比例两个胶囊的任何样式。
- 不改路径胶囊的水平定位、max-width、字体、省略号逻辑（现有
  `max-width: min(70vw, calc(100vw - 200px))` 在 md 及以上宽度已为两侧角落胶囊
  留出足够间隙，768px 边界处仍有约 7px 安全间距）。
- 不改注册方式（`appendTo: "wrapper"`）、resolver 门控与任何组件逻辑。
- 无后端改动、无测试逻辑改动。

## 设计

仅改 [ImageLightbox.vue](../../../frontend/src/components/ImageLightbox.vue)
`<style>` 中 `.pswp__location-label` 一条规则：基准（移动优先）保持
`bottom: 44px`，新增 `min-width: 768px` 媒体查询覆盖为 `bottom: 10px`。

```css
.pswp__location-label {
  position: absolute;
  left: 50%;
  bottom: 44px; /* 窄屏抬高，避开角落两个胶囊 */
  transform: translateX(-50%);
  /* 其余属性不变 */
}

/* 桌面端：与左下拍摄时间、右下缩放比例胶囊对齐到同一基线 */
@media (min-width: 768px) {
  .pswp__location-label {
    bottom: 10px;
  }
}
```

影响面：该元素只在传入 `locationResolver` 时注册，即仅搜索结果灯箱与人物页灯箱
出现；图库普通浏览灯箱不受影响（本来就没有该元素）。

## 测试

- jsdom 不做真实布局、无法断言 CSS 计算值，不新增自动化用例；
  现有 `lightbox-location.spec.ts` 的注册断言（`appendTo: "wrapper"`、
  无 resolver 不注册）保持不变并继续通过。
- 验证：`cd frontend && pnpm test && pnpm build` 全绿；浏览器手动确认
  桌面宽度三胶囊同一基线、窄屏路径胶囊仍抬高且不重叠，浅/深主题与 idle 淡隐
  行为正常。

## YAGNI 记录

曾评估「所有屏幕统一 bottom: 10px、靠 max-width 收窄防重叠」：375px 宽下中间
路径可用宽度仅剩约 100px，几乎必然省略到无信息量，且与角落胶囊间隙为零，
排除。
