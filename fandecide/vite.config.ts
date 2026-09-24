import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

const src = fileURLToPath(new URL('./src', import.meta.url))

// 决策后端就是同仓库的 meal-planner FastAPI (:8000)。
// 用 dev proxy 把 /api 转发过去, 好处有三:
//   1. 浏览器同源 (5188), 完全不碰 CORS
//   2. 后端 Set-Cookie 原样回传, 会话 cookie 自然落在 127.0.0.1 上
//   3. 前端代码里只写 /api/... , 部署时换成 nginx 反代同一套路径即可
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': src },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        withCredentials: true,
      },
    },
  },
  preview: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        withCredentials: true,
      },
    },
  },
})
