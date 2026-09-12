# 小程序构建产物说明

Taro 4 不支持按平台分 `outputRoot`，`miniapp/config/index.ts` 显式把两个平台
输出到不同目录，**否则一方构建会清空另一方**。

| 目录 | 谁生成 | 谁消费 | 怎么开 |
| --- | --- | --- | --- |
| `miniapp/dist/` | `npm run build:weapp` | 微信开发者工具 | 开发者工具里「导入项目」目录选 `miniapp/`（不要选 `dist/`），`project.config.json` 里的 `miniprogramRoot: "dist/"` 会自动定位 |
| `miniapp/dist-h5/` | `npm run build:h5` | 浏览器预览 H5 版本 | `npx serve dist-h5` 或本地静态服务器 |

两个目录都在根 `.gitignore` 里，**不会进版本库**。

---

## 常见报错

### `根据 project.config.json 中 miniprogramRoot 指定的小程序目录 dist/，在该目录下未找到 app.json`

**原因**：上一次 `npm run build:h5` 把 weapp 产物清空了，或开发者工具打开的目录错了。

**修复**：
1. 在 `miniapp/` 根目录跑 `npm run build:weapp`
2. 确认 `miniapp/dist/app.json` 已生成（应该 ~700 B）
3. 在开发者工具里**点「编译」**而不是重新导入项目

**预防**：始终用 `npm run build:h5` / `build:weapp` 触发构建，不要直接调 `taro build`，
也不要混着跑 —— Taro 会把 `outputRoot` 内容整个清空。

### 开发者工具打开的目录选错了

导入项目时项目目录应选 **`miniapp/`**，**不要选 `miniapp/dist/`**。
开发者工具会读 `miniapp/project.config.json` 里的 `miniprogramRoot` 字段，
自动定位到正确目录。

---

## 真机调试的后端地址

后端地址由环境变量 `MP_API_BASE` 驱动，**默认是 `http://127.0.0.1:8000/api`**，
模拟器开箱即用。

| 场景 | 命令 |
| --- | --- |
| 模拟器（默认） | `npm run dev:weapp` |
| 真机调试（局域网） | `MP_API_BASE=http://192.168.x.x:8000/api npm run dev:weapp` |
| 生产发布（HTTPS 备案域名） | `MP_API_BASE=https://app.example.com/api npm run build:weapp` |

启动期若检测到 `https://127.0.0.1` 或「生产构建但默认 HTTP」会在终端打 warn，
提醒你显式指定 `MP_API_BASE`。

`config/base.ts` 集中处理 URL 解析与告警；旧的 `dev.ts` / `prod.ts` 已经合并掉，
因为它们的唯一差异就是这个默认值。

「预览」模式会校验 request 合法域名，http 一定被拦；只有「真机调试」会自动跳过。
生产环境必须用 `MP_API_BASE=https://...` 的备案域名，并在小程序后台登记。

---

## 7. 微信基础库版本（audit B8 收口）

`project.config.json` 与 `project.private.config.json` 的 `libVersion` 当前锁 **`3.17.1`**，
这是**有意保持**，不是漏升级。

**为什么不动**：

- `libVersion` 是开发者工具「详情 → 本地设置」里的调试基准库，**改高会抬高用户可打开
  小程序的最低微信版本门槛**，改低则用不了新 API —— 属产品 / 运营决策，不属技术清理范围。
- 本项目用到的 API（`setBackgroundColor` / `setNavigationBarColor` / `requestSubscribeMessage` /
  `chooseMedia` / `getUserProfile`）在 3.17.1 上全部可用，没有必须升级的诉求。
- 审查报告 B8 只写「建议提升」，未给出目标版本与依据，因此不做无依据的改动。

**什么时候该动**：

1. 微信官方把 3.17.1 标记为停止维护（EOL）；
2. 业务需要 3.17.1 不支持的新 API（届时同步评估被挡在门外的用户占比）；
3. 灰度数据里出现「因版本过低打不开」的反馈且占比 > 1%。

**怎么改**：开发者工具 → 详情 → 本地设置 → 调试基础库，改完两个 `project*.config.json`
的 `libVersion` 会同步；提交前在真机上用最低目标微信版本实测一遍。