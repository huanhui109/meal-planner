import path from 'node:path'
import { defineConfig, type UserConfigExport } from '@tarojs/cli'

import devConfig from './dev'
import prodConfig from './prod'

// shared/ 在 miniapp/ 之外, 需要显式告诉 Taro 的 babel 也要编译它,
// 否则 webpack 会把 TS 源码原样当 JS 解析, 报 "Unexpected token"。
const sharedDir = path.resolve(__dirname, '..', '..', 'shared')

// weapp 与 h5 共用 config.outputRoot(全局, 无法按平台分目录);
// DevTools 的 miniprogramRoot 指向 dist/, 故 weapp 必须留在 dist/,
// h5 单独输出到 dist-h5, 否则互相覆盖会导致 "dist/app.json 找不到"。
//
// 用 TARO_ENV 而不是 process.argv.includes('h5') 的原因:
//   1. Taro 4 在调用 defineConfig 之前已经把 --type 解析到 process.env.TARO_ENV,
//      这是官方约定, 所有内部插件 (mini/h5) 都读这个值
//   2. argv.includes('h5') 在 CI / scripts / npm 嵌套调用时容易误判 (例如
//      父脚本名恰好叫 h5.sh), TARO_ENV 是受控环境变量, 更稳
//   3. 通过 --type=h5 时 TARO_ENV='h5', --type=weapp 时 TARO_ENV='weapp'
const isH5 = process.env.TARO_ENV === 'h5'

export default defineConfig<'webpack5'>(async (merge) => {
  const baseConfig: UserConfigExport<'webpack5'> = {
    projectName: 'meal-planner-miniapp',
    date: '2026-9-10',
    // 375 = 按 iPhone 逻辑宽度设计, 由 pxtransform 转成 rpx (1px -> 2rpx)
    designWidth: 375,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      375: 2,
      828: 1.81 / 2,
    },
    sourceRoot: 'src',
    outputRoot: isH5 ? 'dist-h5' : 'dist',
    plugins: ['@tarojs/plugin-platform-h5'],
    defineConstants: {},
    alias: {
      '@': path.resolve(__dirname, '..', 'src'),
      '@shared': sharedDir,
    },
    copy: {
      patterns: [],
      options: {},
    },
    framework: 'react',
    compiler: {
      type: 'webpack5',
      prebundle: { enable: false },
    },
    cache: { enable: false },
    mini: {
      compile: {
        include: [sharedDir],
      },
      postcss: {
        pxtransform: { enable: true, config: {} },
        cssModules: { enable: false },
      },
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      compile: {
        include: [sharedDir],
      },
      postcss: {
        autoprefixer: { enable: true, config: {} },
        pxtransform: { enable: true, config: {} },
        cssModules: { enable: false },
      },
    },
  }

  if (process.env.NODE_ENV === 'development') {
    return merge({}, baseConfig, devConfig)
  }
  return merge({}, baseConfig, prodConfig)
})
