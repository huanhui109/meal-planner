/**
 * 共享层出口
 *
 * 两端都通过 `@shared/...` 别名引用, 这里不依赖任何框架 (没有 React / Taro / axios),
 * 所以同一份业务逻辑能在浏览器和小程序里跑。
 */
export * from './types'
export * from './brand'
export * from './format'
export * from './labels'
export * from './next-step'
export * from './today'
export * from './endpoints'
export { tokens, numericFont } from './tokens'
export type { Tokens } from './tokens'
