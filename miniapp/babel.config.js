// Taro 的 babel 预设: 负责把 JSX 转成小程序可识别的东西
module.exports = {
  presets: [
    [
      'taro',
      {
        framework: 'react',
        ts: true,
        compiler: 'webpack5',
      },
    ],
  ],
}
