import os from 'node:os'
import type { UserConfigExport } from '@tarojs/cli'

/**
 * 后端 API 地址
 *
 * 优先级: 显式环境变量 MP_API_BASE > (dev) 本机局域网 IP > 127.0.0.1 兜底
 *
 * | MP_API_BASE   | 实际指向 | 场景 |
 * |---------------|----------|------|
 * | (未设)        | http://<局域网IP>:8000/api | 默认: 模拟器 + 真机调试都能用 |
 * | (未设, 取不到 IP) | http://127.0.0.1:8000/api | 离线兜底, 仅模拟器可用 |
 * | http://192.168.1.10:8000/api | 指定局域网 IP | 多网卡 / 虚拟机时手动指定 |
 * | https://app.example.com/api | 生产, 必须 HTTPS + 已备案 | 上线 |
 *
 * ⚠ 为什么默认不再写死 127.0.0.1:
 *   真机调试时包是跑在**手机**上的, 127.0.0.1 是手机自己, 请求必然
 *   "网络连接失败" —— 后端明明在电脑上跑得好好的。默认改成局域网 IP 后,
 *   同一 Wi-Fi 下的真机直连可用; 模拟器/开发者工具访问局域网 IP 同样通
 *   (电脑访问自己的局域网 IP 没有区别), 所以不会牺牲本地体验。
 *
 * 历史踩坑:
 *   - 旧 prod.ts 默认 https://127.0.0.1:8000/api, 本地后端无 SSL →
 *     GET https://... net::ERR_SSL_PROTOCOL_ERROR
 *   - 默认 HTTPS 在没有备案域名时永远跑不通, 把它当 fallback 是错的;
 *     正确做法是默认 HTTP (本地一定可用), HTTPS 只在显式 MP_API_BASE 时启用
 *   - 旧 dev.ts / prod.ts 唯一差异就是这个默认值, 合并掉
 */

/** 取第一个非回环 IPv4 (Wi-Fi / 有线); 拿不到返回 null */
function lanAddress(): string | null {
  const interfaces = os.networkInterfaces()
  for (const name of Object.keys(interfaces)) {
    for (const net of interfaces[name] || []) {
      // Node 18+ 的 family 是 'IPv4' 字符串, 老版本是数字 4, 两种都兼容
      // (类型定义只认字符串, 所以这里用 unknown 过渡再比较)
      const family = net.family as unknown
      const isV4 = family === 'IPv4' || family === 4
      if (isV4 && !net.internal) return net.address
    }
  }
  return null
}

function resolveApiBase(): string {
  const explicit = process.env.MP_API_BASE
  if (explicit) return explicit
  const lan = lanAddress()
  return lan ? `http://${lan}:8000/api` : 'http://127.0.0.1:8000/api'
}

const API_BASE_URL = resolveApiBase()
const IS_LOCAL = /127\.0\.0\.1|localhost/.test(API_BASE_URL)

// 启动期给出明确提示, 避免用户在错误的环境下调试
if (API_BASE_URL.startsWith('https://127.0.0.1') || API_BASE_URL.startsWith('https://localhost')) {
  // eslint-disable-next-line no-console
  console.warn(
    '[miniapp config] API 仍指向 https://127.0.0.1, 本地后端无 SSL 会报 ERR_SSL_PROTOCOL_ERROR',
  )
  // eslint-disable-next-line no-console
  console.warn('[miniapp config] 显式传 MP_API_BASE=http://<电脑IP>:8000/api 即可, 详见 miniapp/BUILD.md')
}
if (!process.env.MP_API_BASE) {
  // eslint-disable-next-line no-console
  console.warn(`[miniapp config] API = ${API_BASE_URL} (自动探测, 未设 MP_API_BASE)`)
  if (IS_LOCAL) {
    // eslint-disable-next-line no-console
    console.warn('[miniapp config] ⚠ 没探测到局域网 IP, 真机调试会连不上; 请显式传 MP_API_BASE=http://<电脑IP>:8000/api')
  } else {
    // eslint-disable-next-line no-console
    console.warn('[miniapp config] 真机调试请确保手机与电脑在同一 Wi-Fi, 并在开发者工具勾选「不校验合法域名」')
  }
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