# 小程序三项修复 · 交付说明（2026-09-11）

针对本轮三个需求：① 冰箱页点击报错、无数据；② 周菜单人机交互重构；③ 品牌配色/Logo 资产。
以下为根因、改动、验证，文件均可直接在仓库查看。

---

## ① 冰箱页「点击报错、无法显示数据」

**根因（契约不匹配，已用真实后端验证）**
- 后端 `GET /api/inventory` 响应信封里的 `data` 是 **对象** `{ total, expiring_count, items }`，不是裸数组。
- 小程序 `miniapp/src/lib/api.ts` 的 `listInventory` 却声明成 `http.get<InventoryItem[]>`；
  而 `http.get` 返回的就是信封里的 `data`（那个对象）。
- 冰箱页 `setItems((await listInventory()) || [])` 把**对象**当数组存进 `items`，
  渲染时 `items.filter(...)` → `TypeError: items.filter is not a function` → 整页崩，表现为「报错且无数据」。
- 对照 H5 `frontend/src/api/inventory.ts`：它返回同样的对象，页面用 `result.items` / `result.expiring_count` —— 小程序这侧写错了契约。

**改动**
- `miniapp/src/lib/api.ts`：`listInventory` 改为
  `http.get<{ total: number; expiring_count: number; items: InventoryItem[] }>(...)`。
- `miniapp/src/pages/fridge/index.tsx`：
  `const result = await listInventory(); setItems(result.items || [])`。

**验证（真实后端）**
```
GET /api/health   → 200 {"status":"ok","database":"ok","version":"0.2.0"}
GET /api/inventory → 401（无 token；路由存在）
dev-login 后 GET /api/inventory →
  {"code":0,"message":"success","data":{"total":0,"expiring_count":0,"items":[]}}
```
响应形状与修后取值一致；`tsc --noEmit` 0 错；weapp 重新构建成功。

---

## ② 周菜单页人机交互重构（闭环 / 流畅 / 不冗余）

**改动**：`miniapp/src/pages/menu/index.tsx`、`miniapp/src/lib/meal-actions.ts`、`miniapp/src/app.scss`。

1. **去冗余**：删除总览卡里与底部重复的「重新生成」，全页只保留一次（页面底部）。
2. **流畅（乐观更新）**：换一道 / 锁定 / 做完了 不再整页 `load()` 闪烁，
   改为本地 `patchMeal` / `bumpCooked` 即时更新；只有「生成 / 确认」这类整周级动作才重新拉取。
   `askReplaceRecipe` 改为返回换好后的 `MenuDetail`（含「换回上一道」的最终结果），页面 `setMenu` 即可。
3. **闭环（可返回 / 可撤销）**：
   - 不在今天时，星期条最前出现「今天」快捷药丸，一键回到今天；
   - 「今天」那格加「今」角标，一眼可辨；
   - 「做完了」后 6 秒内该行出现「撤销」（库存还原），操作可逆。

**验证**：`tsc --noEmit` 0 错；`taro build --type weapp` 编译成功；`dist/` 中 ES5 不兼容的 `??`/`?.` 计数 = 0。

---

## ③ 从 H5 / 共享层提取小程序品牌资产（配色 + Logo）

**结论：资产已存在并已接入，本轮做了「去漂移 + 建档」**（详见 `docs/miniapp-brand-assets.md`）。

- 配色：`shared/tokens.ts` → `miniapp/src/styles/_tokens.scss`（`$color-*` 语义色 + `$brand-*` 品牌色 + `page{}` 上的 CSS 变量）。
- Logo：`scripts/gen_logo.mjs` → `miniapp/src/lib/logo.ts`（`LOGO_MARK_DATA_URI`，登录页在用）、
  `miniapp/src/assets/logo-mark.png`、`share-icon.png`；文案在 `shared/brand.ts`。
- **发现问题**：`node scripts/gen_logo.mjs --check` 报 PNG 与 `logo.ts` 与脚本不一致（CI 会挂）——光栅产物是旧脚本留下的。
- **修复**：`node scripts/gen_logo.mjs` 重新生成全部产物；`node scripts/gen_tokens.mjs --check` → 两份产物均 ✓。
- 说明：TabBar 图标是 `miniapp/src/custom-tab-bar/index.tsx` 里用 `View` 画的几何形，不用图片；
  小程序里也不建议 `<Image src="*.svg">`，统一走 base64 PNG。

---

## 附：本地联调须知

- 数据库在跑：`127.0.0.1:3307`；后端用 `bash scripts/service.sh start backend` 启动（健康检查 200）。
- 已把 `scripts/service.sh` 的 `BACKEND_HOST` 默认值由 `127.0.0.1` 改回 `0.0.0.0`（与头部注释一致，真机才能用电脑 LAN IP 连上）。
- **重要**：请在**自己的终端**里启动后端再联调。工具沙箱里起的后台进程会在回合结束后被回收，不能长期驻留。
- 真机联调请用「真机调试」而非「预览」，并确保手机与电脑同一 WiFi（电脑 LAN IP：`192.168.3.83`）。
