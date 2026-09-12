import type { UserConfigExport } from '@tarojs/cli'

/**
 * 后端 API 地址
 *
 * 优先级: 显式环境变量 > 默认值
 *
 * | NODE_ENV     | MP_API_BASE   | 实际指向 |
 * |--------------|---------------|----------|
 * | development  | (未设)        | http://127.0.0.1:8000/api  (dev:weapp 默认) |
 * | production   | (未设)        | http://127.0.0.1:8000/api  (build:weapp 默认, 本地能跑) |
 * | *            | http://192.168.1.10:8000/api | 真机调试, 局域网 IP |
 * | *            | https://app.example.com/api | 生产部署, 必须 HTTPS + 已备案 |
 *
 * 历史踩坑:
 *   - 旧 prod.ts 默认 https://127.0.0.1:8000/api, 本地后端无 SSL →
 *     GET https://... net::ERR_SSL_PROTOCOL_ERROR
 *   - 默认 HTTPS 在没有备案域名时永远跑不通, 把它当 fallback 是错的;
 *     正确做法是默认 HTTP (本地一定可用), HTTPS 只在显式 MP_API_BASE 时启用
 *   - 旧 dev.ts / prod.ts 唯一差异就是这个默认值, 合并掉
 */
function resolveApiBase(): string {
  if (process.env.MP_API_BASE) return process.env.MP_API_BASE
  return 'http://127.0.0.1:8000/api'
}

const API_BASE_URL = resolveApiBase()

// 启动期给出明确提示, 避免用户在错误的环境下调试
if (API_BASE_URL.startsWith('https://127.0.0.1') || API_BASE_URL.startsWith('https://localhost')) {
  // eslint-disable-next-line no-console
  console.warn(
    '[miniapp config] API 仍指向 https://127.0.0.1, 本地后端无 SSL 会报 ERR_SSL_PROTOCOL_ERROR',
  )
  // eslint-disable-next-line no-console
  console.warn('[miniapp config] 显式传 MP_API_BASE=http://<电脑IP>:8000/api 即可, 详见 miniapp/BUILD.md')
}
if (API_BASE_URL.startsWith('http://') && process.env.NODE_ENV === 'production' && !process.env.MP_API_BASE) {
  // eslint-disable-next-line no-console
  console.warn('[miniapp config] 生产构建但默认 HTTP, 上线前请 MP_API_BASE=https://<备案域名>/api 重构')
}

export default {
  defineConstants: {
    API_BASE_URL: JSON.stringify(API_BASE_URL),
  },
  mini: {},
  h5: {},
} satisfies UserConfigExport<'webpack5'>