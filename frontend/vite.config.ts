/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  test: {
    // 共享层 (../shared) 是两端唯一真源, 这里跑它的纯函数测试
    include: ['tests/**/*.test.ts', 'src/**/*.test.ts'],
    environment: 'node',
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // H5 与小程序共享的业务层 (类型/格式化/下一步规则/设计令牌)
      '@shared': fileURLToPath(new URL('../shared', import.meta.url)),
    },
  },
  build: {
    // 手机 H5 首屏: 把体积最大的 antd / react 拆成独立 chunk, 便于并行加载与长期缓存
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
        },
      },
    },
    chunkSizeWarningLimit: 800,
  },
  server: {
    port: 5173,
    // shared/ 在 frontend/ 之外, 允许 dev server 读取上一级目录
    fs: { allow: ['..'] },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
