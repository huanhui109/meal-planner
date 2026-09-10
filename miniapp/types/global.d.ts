/** 由 config/dev.ts / config/prod.ts 注入 */
declare const API_BASE_URL: string

declare module '*.scss' {
  const content: string
  export default content
}
