import type { UserConfigExport } from '@tarojs/cli'

/**
 * 生产: 必须是已完成 ICP 备案的 HTTPS 域名, 并在小程序后台
 * 「开发设置 -> 服务器域名 -> request 合法域名」里登记, 否则真机请求会被拦截。
 */
export default {
  defineConstants: {
    API_BASE_URL: JSON.stringify('https://192.168.3.83:8000/api'),
  },
  mini: {},
  h5: {},
} satisfies UserConfigExport<'webpack5'>
