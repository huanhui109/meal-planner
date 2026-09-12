# 上线前 Checklist（内测灰度）

> 适用: 30-50 种子用户内测灰度
> 计划文档: `/Users/jason/.workbuddy/plans/blazing-thunder-tesla-TzZ3ghtf.md`

---

## 一、合规（必做 ⏳ 法务）

- [ ] `docs/legal/privacy.md` 法务签字（看 `REVIEW.md`）
- [ ] `docs/legal/terms.md` 法务签字
- [ ] 运营方公司主体信息填入隐私 / 条款
- [ ] 客服微信号绑定（微信小程序后台 → 客服）
- [ ] 隐私协议 URL 配置（微信小程序后台 → 设置 → 用户隐私协议）

---

## 二、微信小程序后台配置

- [ ] 体验成员 → 拉白名单（30-50 种子用户微信 openid）
- [ ] 开发设置 → 服务器域名：填 `https://<ngrok 或 cloudflared 域名>`（request 合法域名 / uploadFile 合法域名）
- [ ] 开发设置 → 业务域名：填 HTTPS 域名
- [ ] 类目选择：工具 → 效率（订阅消息模板需要这个类目）
- [ ] 订阅消息模板：申请 1 个「长期订阅」模板
- [ ] 客服：绑定客服微信号

---

## 三、后端部署（必做 ⏳ 运维）

- [ ] HTTPS 证书：自签（内测）/ 备案后正式证书
- [ ] 域名：ngrok / cloudflared 临时隧道（内测）/ 备案域名（正式）
- [ ] 后端服务：`make ops` → 启动 backend / frontend / db
- [ ] 数据库迁移：`make migrate`（新增 6 个迁移 0008-0013）
- [ ] 环境变量：`.env` 含 `APP__AUTH__JWT_SECRET` ≥ 32 字符 / `APP__BASE_URL` / `APP__DATABASE__URL`
- [ ] 至少一个 LLM Key 在线：`GLM4_API_KEY` / `QWEN_API_KEY` / `DEEPSEEK_API_KEY` 任一
- [ ] 飞书机器人配置（如启用推送）：`APP__FEISHU__*` 一组

---

## 四、小程序构建（必做 ⏳ 开发）

- [ ] `cd miniapp && npm install`
- [ ] `npm run build:weapp`（输出 `miniapp/dist/`）
- [ ] 微信开发者工具 → 导入项目 → 目录选 `miniapp/`（不要选 `miniapp/dist/`）
- [ ] 详情 → 本地设置 → 「不校验合法域名…」已勾选
- [ ] 编译成功，控制台无 `invalid file` / `s.setSelected is not a function` 错误

---

## 五、端到端冒烟（必做 ⏳ QA）

5 个核心路径：

- [ ] 登录路径：未登录 → 登录页 → 微信一键登录 / 本地开发登录 → 今日页
- [ ] 生成菜单：今日页 → 「下一步：生成菜单」→ 等待 3s × N → 菜单显示
- [ ] 标记已做：今日页 → 今晚菜单 → 「做完了扣库存」→ toast 反馈
- [ ] 拍照识别：今日页 → 「拍照入库冰箱」→ 选照片 → 识别 → 改食材 → 入库
- [ ] 退登：我的 → 「退出登录」→ 二次确认 → 回登录页

---

## 六、可观测性（必做 ⏳ 运维）

- [ ] `GET /api/health` 返回 `{version, scheduler_running, last_event_at, last_menu_generate_at}`
- [ ] 埋点 SDK 上报：登录 / 生成 / 换菜 / 拍照 / 退登 5 个关键行为有数据
- [ ] 崩溃自动上报：`App.onError` + `Taro.onUnhandledRejection` 接住

---

## 七、灰度观察（首周 ⏳ 运营）

每日记录：

- [ ] DAU（埋点统计）
- [ ] 菜单生成成功率（埋点统计）
- [ ] 拍照识别修正率（用户改了几个食材）
- [ ] 反馈提交数 / 类型分布（`feedback` 表）
- [ ] 闪退 / 异常（埋点统计）
- [ ] 客服会话数 / 解决率

---

## 八、灰度通过标准（晋级到正式上线）

- [ ] 7 天内零 P0 闪退
- [ ] 关键路径成功率 ≥ 95%
- [ ] 反馈闭环：每条反馈 24h 内有响应
- [ ] 用户留存：7 日留存 ≥ 40%

满足以上 4 条可启动 ICP 备案 + 微信审核正式上线。
