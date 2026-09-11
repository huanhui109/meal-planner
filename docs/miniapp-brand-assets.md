# 小程序品牌资产（配色 + Logo）

> 从 H5 / 共享层提取，供 `miniapp` 直接使用。**唯一真源在代码里**，本文只做索引与使用说明；
> 改色 / 改标只需改源文件再跑生成脚本，不要在本文里手改数值。

## 1. 唯一真源

| 资产 | 源文件 | 生成物 | 生成命令 |
| --- | --- | --- | --- |
| 语义色 + 品牌色 + 字号/圆角/阴影/动效 | `shared/tokens.ts` | `miniapp/src/styles/_tokens.scss`（SCSS 变量 + `page{}` 上的 CSS 变量） | `node scripts/gen_tokens.mjs` |
| Logo（平底锅颠荷包蛋） | `shared/tokens.ts` 的 `brand` 段 + `scripts/gen_logo.mjs` 几何定义 | `miniapp/src/lib/logo.ts`、`miniapp/src/assets/logo-mark.png`、`share-icon.png` | `node scripts/gen_logo.mjs` |
| 品牌文案（名称/全名/主张） | `shared/brand.ts` | —（两端直接 import） | — |

两端（H5 `frontend/`、小程序 `miniapp/`）都从 `shared/` 取值，CI 跑 `--check`，生成物与源不一致就失败，所以两端不会漂移。

```bash
# 校验（CI 同款，发现不一致会非 0 退出）
node scripts/gen_tokens.mjs --check
node scripts/gen_logo.mjs --check
# 重新生成
node scripts/gen_tokens.mjs && node scripts/gen_logo.mjs
```

## 2. 配色

### 2.1 语义色（承载 95% 面积，中性灰为主）

| 令牌 | 值 | 用途 |
| --- | --- | --- |
| `$color-bg` | `#e9e9ee` | 页面外底色 |
| `$color-screen` | `#f7f7f9` | 屏幕底色 |
| `$color-card` | `#ffffff` | 卡片 |
| `$color-ink` | `#1c1c1e` | 主文字 / 主按钮（纯黑胶囊） |
| `$color-ink2` | `#8e8e93` | 次级文字 |
| `$color-ink3` | `#c7c7cc` | 占位 / 禁用 |
| `$color-line` | `#efeff2` | 分隔线 |
| `$color-fill` | `#f2f2f4` | 浅填充（餐次行等） |
| `$color-accent` / `-ink` / `-soft` | `#34c759` / `#1e7d3c` / `rgba(52,199,89,.12)` | 绿 = 完成 / 充足 |
| `$color-warn` / `-ink` / `-soft` | `#ff9f0a` / `#c77800` / `rgba(255,159,10,.12)` | 橙 = 临期 / 超支 |
| `$color-danger` / `-soft` | `#ff3b30` / `rgba(255,59,48,.12)` | 红 = 错误 |
| `$color-glass` | `rgba(255,255,255,.82)` | 悬浮毛玻璃胶囊 |

### 2.2 品牌色（只服务 Logo，不参与语义配色）

| 令牌 | 值 | 部位 |
| --- | --- | --- |
| `$brand-frame-dark` | `#1c1c1e` | 容框（浅色场景用，默认版 logo 的深色圆角方） |
| `$brand-frame` | `#ffffff` | 容框（深色背景用，反白版） |
| `$brand-pan` | `#3b4048` | 锅身 |
| `$brand-pan-rim` / `-inner` | `#6b7280` / `#2b2f35` | 锅沿 / 锅内 |
| `$brand-pan-light` / `-rim` / `-inner` | `#e8e8ea` / `#f4f4f6` / `#c9c9ce` | 深色底上的浅色锅 |
| `$brand-wood` | `#c9824a` | 锅柄木色 |
| `$brand-yolk` / `-light` | `#f6a623` / `#ffc861` | 蛋黄 / 高光 |
| `$brand-motion` | `#f2b872` | 颠动弧线 |
| `$brand-egg` / `-line` | `#ffffff` / `#dadada` | 蛋白 / 蛋白描边 |

### 2.3 小程序里怎么用

```scss
// 页面/组件样式里直接引 SCSS 变量（构建期展开，无运行时开销）
@import '../styles/tokens';
.my-title { color: $color-ink; font-size: $font-heading; background: $color-card; }
```

```tsx
// 需要运行时可覆盖时用 CSS 变量（page{} 上已暴露）
<View style={{ color: 'var(--color-ink)' }} />
```

## 3. Logo

一个符号：**平底锅颠荷包蛋**（白底容框 / 深色锅身 / 木柄 / 蛋黄），共 4 种配色版本。

| 文件 | 版本 | 适用 |
| --- | --- | --- |
| `miniapp/src/lib/logo.ts` → `LOGO_MARK_DATA_URI` | 默认（深色容框）base64 PNG | **小程序首选**：iOS/Android 表现最稳，无需配 loader |
| `miniapp/src/assets/logo-mark.png` | 默认 192px | 需要本地图片资源时 |
| `miniapp/src/assets/share-icon.png` | 5:4 分享卡 | 分享/转发封面 |
| `assets/logo/logo-mark.svg` | 默认 | 矢量稿（H5/文档用） |
| `assets/logo/logo-mark-inverse.svg` | 反白（白容框） | 深色背景 |
| `assets/logo/logo-mono.svg` | 单色白剪影 | 单色印刷 / 深色底 |
| `assets/logo/logo-full.svg` | 横版「标 + 每周鲜 · AI 营养菜谱」 | 品牌露出 |

### 小程序里怎么用

```tsx
import { Image } from '@tarojs/components'
import { LOGO_MARK_DATA_URI } from '../../lib/logo'
// 注意：小程序不用 <Image src="xxx.svg">（本地 svg 支持不稳），用 base64 PNG 最稳
<Image className="login-logo" src={LOGO_MARK_DATA_URI} mode="aspectFit" />
```

现网接入点：`miniapp/src/pages/login/index.tsx`（登录页 logo + `brand.name` / `fullName` / `description`）。

> 说明：底部 TabBar 的图标不是图片，而是 `miniapp/src/custom-tab-bar/index.tsx`
> 里用 `View` 画的极简几何形（home/calendar/basket/box），跟主题色一起变，包体积为 0，所以不涉及 logo 图片资源。

## 4. 变更 Checklist

- [ ] 改色：只改 `shared/tokens.ts` → `node scripts/gen_tokens.mjs` → 提交 `_tokens.scss` / `tokens.css`。
- [ ] 改标：只改 `scripts/gen_logo.mjs`（几何/取色）→ `node scripts/gen_logo.mjs` → 提交 SVG/PNG/`logo.ts`。
- [ ] 改文案：只改 `shared/brand.ts`（+ `config/default.yaml`）。
- [ ] 提交前跑两个 `--check`，避免 CI 挂。
