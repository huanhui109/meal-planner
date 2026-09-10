import type { UserConfigExport } from '@tarojs/cli'

/** 开发期: 指向本机后端 (微信开发者工具需勾选"不校验合法域名"才能连 http) */
export default {
  defineConstants: {
    API_BASE_URL: JSON.stringify('http://127.0.0.1:8000/api'),
  },
  mini: {},
  h5: {},
} satisfies UserConfigExport<'webpack5'>
