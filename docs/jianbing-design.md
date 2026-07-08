# 煎饼设计说明

## 需求

Issue #1 的原始需求是“给我一张煎饼”。当前仓库没有既有应用框架或素材规范，因此本次交付先提供一张可直接使用的煎饼视觉资产，并补充设计说明，作为后续页面、卡片、道具或内容展示的基础。

## 设计目标

- 主体清晰：画面第一眼能识别为中式煎饼。
- 食欲感明确：保留金黄饼皮、鸡蛋层、葱花、芝麻和酱料等关键细节。
- 使用范围宽：适合 README、原型稿、食物卡片、活动页或后续应用界面。
- 干扰少：避免人物、包装、文字、水印和复杂餐具抢占主体。

## 视觉方案

资产文件：`assets/jianbing.png`

风格采用写实食品摄影。构图为三分之四俯视角，煎饼居中放置在暖色中性桌面上，使用柔和自然光和轻微真实阴影来增强质感。画面保留足够留白，方便后续在 UI 中裁切或叠加标题。

## 生成提示词

```text
Use case: photorealistic-natural
Asset type: project visual asset for a lightweight repository design deliverable
Primary request: 一张煎饼
Subject: A freshly made Chinese jianbing crepe, folded and ready to serve, with visible golden crisp edges, egg layer, scallions, sesame seeds, and savory sauce peeking from the fold.
Composition: Three-quarter overhead food photography, centered subject with generous padding, appetizing but realistic texture, no hands or utensils.
Scene/backdrop: Clean warm neutral tabletop, soft natural window light, subtle real shadow.
Quality: High-resolution realistic food photograph, sharp details, natural colors.
Avoid: text, watermark, logo, packaging, extra dishes, people.
```

## 验收标准

- 图片文件存在于 `assets/jianbing.png`。
- 画面主体是煎饼，且没有文字、水印或品牌标识。
- README 能直接指向资产和设计说明。
- 后续若扩展为页面或组件，应优先复用该资产，而不是重新引入无关视觉风格。
