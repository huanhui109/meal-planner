import './styles/tokens.css'
import './global.css'
// Demo 设计层: 令牌映射 + 组件类, 必须压在 tokens/global 之后
import './styles/demo.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { buildAntdTheme } from './theme'
import { initTheme, useThemeStore } from './stores/useThemeStore'

// 在 React 挂载前先把 data-theme 写到 html, 避免首屏从默认暗色闪一下到用户偏好
initTheme()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
})

/**
 * 跟随主题的 ConfigProvider 包装: 读 store 里的 `applied` 字段 (而非 `theme`),
 * 这样 auto 模式下 antd 也能拿到解析后的 cool/dark。html[data-theme] 已经把
 * var(--color-*) 切了, antd 这一层也跟过来才能整体统一。
 */
const ThemedProviders: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const applied = useThemeStore((s) => s.applied)
  return <ConfigProvider theme={buildAntdTheme(applied)} locale={zhCN}>{children}</ConfigProvider>
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemedProviders>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ThemedProviders>
  </React.StrictMode>,
)