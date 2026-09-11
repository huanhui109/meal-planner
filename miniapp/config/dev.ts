import type { UserConfigExport } from '@tarojs/cli'

/**
 * 开发期后端地址
 *
 * 默认 `http://127.0.0.1:8000/api`(开发者工具模拟器可用, 因为模拟器跑在本机)。
 * 但真机预览/真机调试时, 手机上的小程序访问不到电脑的 127.0.0.1, 必须换成
 * 电脑在局域网里的 IP, 例如:
 *
 *   MP_API_BASE=http://192.168.1.23:8000/api npm run dev:weapp
 *
 * 注意: 「预览」模式会校验 request 合法域名, http 一定被拦; 只有「真机调试」
 * 模式会自动跳过域名校验。正式真机验证请走 config/prod.ts 的 HTTPS 备案域名。
 */
const API_BASE_URL = process.env.MP_API_BASE || 'http://127.0.0.1:8000/api'

export default {
  defineConstants: {
    API_BASE_URL: JSON.stringify(API_BASE_URL),
  },
  mini: {},
  h5: {},
} satisfies UserConfigExport<'webpack5'>
