/**
 * 客户端版本号 —— 埋点的 app_version 字段 (R-16a)
 *
 * 为什么必须打真实版本号: event 表现有 91 行的 app_version 100% 是 `unknown`,
 * 于是"这个问题是 1.1 引入的还是 1.2 引入的"根本分不出来, 灰度结论也没法按版本切片。
 * R-16(layout_version 服务端下发)解决"新版好不好", R-16a 解决"是哪个版本的客户端",
 * 两件事不能合并成一个字段。
 *
 * 为什么是常量而不是 import package.json:
 *   Vite 只把 `VITE_` 前缀的变量注入 import.meta.env, 读不到 package.json 的 version;
 *   为了它去改 vite.config.ts 加 define, 等于把"读版本号"这件事绑死在构建配置上。
 *   常量的代价是可能与 package.json 漂移 —— 由 tests/app-version.test.ts 钉住,
 *   版本升级时忘了同步会在测试里红出来。
 */
export const APP_VERSION = '2.8.0'
