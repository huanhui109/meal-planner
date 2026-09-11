/**
 * 内联样式的尺寸单位
 *
 * Taro 的 pxtransform 只处理 .scss/.css 文件, **JSX 内联 style 里的裸数字不会被转换**。
 * 结果是: 写在样式里的尺寸会随屏幕宽度缩放 (px -> rpx), 而内联的数字永远是一个固定
 * 的物理值 —— 小屏 (320) 挤爆、大屏 (428) 偏小, 两边还会互相错位。
 *
 * 所有必须留在 JSX 里的尺寸 (按状态算出来的值、图表几何等) 都过一遍 px(),
 * 由 designWidth 375 换算成 rpx, 与样式文件保持一致。
 */
import Taro from '@tarojs/taro'

export const px = (n: number): string => Taro.pxTransform(n)
