# 滤镜资产许可

## 内置合成预设（warm.cube / cool.cube / mono.cube）

由 `scripts/gen-builtin-luts.mjs` 程序化生成，为本项目自带的 synthetic
preset，随仓库以 MIT 许可分发。它们用于打通管线，不是真实胶片模拟。

## 后续加入的真实 LUT

每一支真实胶片 LUT 丢进本目录时，必须在此追加：
- 文件名列
- 原始来源 URL
- 许可证（个人免费 / 商用条款）
- 是否允许随仓库分发

未确认许可的 LUT 不得提交。
