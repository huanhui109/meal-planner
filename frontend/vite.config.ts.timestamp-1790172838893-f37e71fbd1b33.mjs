// vite.config.ts
import { defineConfig } from "file:///Users/jason/Documents/project/meal-planner/frontend/node_modules/vite/dist/node/index.js";
import react from "file:///Users/jason/Documents/project/meal-planner/frontend/node_modules/@vitejs/plugin-react/dist/index.js";
import { fileURLToPath, URL } from "node:url";
var __vite_injected_original_import_meta_url = "file:///Users/jason/Documents/project/meal-planner/frontend/vite.config.ts";
var vite_config_default = defineConfig({
  plugins: [react()],
  test: {
    // 共享层 (../shared) 是两端唯一真源, 这里跑它的纯函数测试
    include: ["tests/**/*.test.ts", "src/**/*.test.ts"],
    environment: "node"
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", __vite_injected_original_import_meta_url)),
      // H5 与小程序共享的业务层 (类型/格式化/下一步规则/设计令牌)
      "@shared": fileURLToPath(new URL("../shared", __vite_injected_original_import_meta_url))
    }
  },
  build: {
    // 手机 H5 首屏: 把体积最大的 antd / react 拆成独立 chunk, 便于并行加载与长期缓存
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          antd: ["antd", "@ant-design/icons"]
        }
      }
    },
    chunkSizeWarningLimit: 800
  },
  server: {
    port: 5173,
    // shared/ 在 frontend/ 之外, 允许 dev server 读取上一级目录
    fs: { allow: [".."] },
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true
      }
    }
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcudHMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCIvVXNlcnMvamFzb24vRG9jdW1lbnRzL3Byb2plY3QvbWVhbC1wbGFubmVyL2Zyb250ZW5kXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ZpbGVuYW1lID0gXCIvVXNlcnMvamFzb24vRG9jdW1lbnRzL3Byb2plY3QvbWVhbC1wbGFubmVyL2Zyb250ZW5kL3ZpdGUuY29uZmlnLnRzXCI7Y29uc3QgX192aXRlX2luamVjdGVkX29yaWdpbmFsX2ltcG9ydF9tZXRhX3VybCA9IFwiZmlsZTovLy9Vc2Vycy9qYXNvbi9Eb2N1bWVudHMvcHJvamVjdC9tZWFsLXBsYW5uZXIvZnJvbnRlbmQvdml0ZS5jb25maWcudHNcIjsvLy8gPHJlZmVyZW5jZSB0eXBlcz1cInZpdGVzdC9jb25maWdcIiAvPlxuaW1wb3J0IHsgZGVmaW5lQ29uZmlnIH0gZnJvbSAndml0ZSdcbmltcG9ydCByZWFjdCBmcm9tICdAdml0ZWpzL3BsdWdpbi1yZWFjdCdcbmltcG9ydCB7IGZpbGVVUkxUb1BhdGgsIFVSTCB9IGZyb20gJ25vZGU6dXJsJ1xuXG5leHBvcnQgZGVmYXVsdCBkZWZpbmVDb25maWcoe1xuICBwbHVnaW5zOiBbcmVhY3QoKV0sXG4gIHRlc3Q6IHtcbiAgICAvLyBcdTUxNzFcdTRFQUJcdTVDNDIgKC4uL3NoYXJlZCkgXHU2NjJGXHU0RTI0XHU3QUVGXHU1NTJGXHU0RTAwXHU3NzFGXHU2RTkwLCBcdThGRDlcdTkxQ0NcdThERDFcdTVCODNcdTc2ODRcdTdFQUZcdTUxRkRcdTY1NzBcdTZENEJcdThCRDVcbiAgICBpbmNsdWRlOiBbJ3Rlc3RzLyoqLyoudGVzdC50cycsICdzcmMvKiovKi50ZXN0LnRzJ10sXG4gICAgZW52aXJvbm1lbnQ6ICdub2RlJyxcbiAgfSxcbiAgcmVzb2x2ZToge1xuICAgIGFsaWFzOiB7XG4gICAgICAnQCc6IGZpbGVVUkxUb1BhdGgobmV3IFVSTCgnLi9zcmMnLCBpbXBvcnQubWV0YS51cmwpKSxcbiAgICAgIC8vIEg1IFx1NEUwRVx1NUMwRlx1N0EwQlx1NUU4Rlx1NTE3MVx1NEVBQlx1NzY4NFx1NEUxQVx1NTJBMVx1NUM0MiAoXHU3QzdCXHU1NzhCL1x1NjgzQ1x1NUYwRlx1NTMxNi9cdTRFMEJcdTRFMDBcdTZCNjVcdTg5QzRcdTUyMTkvXHU4QkJFXHU4QkExXHU0RUU0XHU3MjRDKVxuICAgICAgJ0BzaGFyZWQnOiBmaWxlVVJMVG9QYXRoKG5ldyBVUkwoJy4uL3NoYXJlZCcsIGltcG9ydC5tZXRhLnVybCkpLFxuICAgIH0sXG4gIH0sXG4gIGJ1aWxkOiB7XG4gICAgLy8gXHU2MjRCXHU2NzNBIEg1IFx1OTk5Nlx1NUM0RjogXHU2MjhBXHU0RjUzXHU3OUVGXHU2NzAwXHU1OTI3XHU3Njg0IGFudGQgLyByZWFjdCBcdTYyQzZcdTYyMTBcdTcyRUNcdTdBQ0IgY2h1bmssIFx1NEZCRlx1NEU4RVx1NUU3Nlx1ODg0Q1x1NTJBMFx1OEY3RFx1NEUwRVx1OTU3Rlx1NjcxRlx1N0YxM1x1NUI1OFxuICAgIHJvbGx1cE9wdGlvbnM6IHtcbiAgICAgIG91dHB1dDoge1xuICAgICAgICBtYW51YWxDaHVua3M6IHtcbiAgICAgICAgICByZWFjdDogWydyZWFjdCcsICdyZWFjdC1kb20nLCAncmVhY3Qtcm91dGVyLWRvbSddLFxuICAgICAgICAgIGFudGQ6IFsnYW50ZCcsICdAYW50LWRlc2lnbi9pY29ucyddLFxuICAgICAgICB9LFxuICAgICAgfSxcbiAgICB9LFxuICAgIGNodW5rU2l6ZVdhcm5pbmdMaW1pdDogODAwLFxuICB9LFxuICBzZXJ2ZXI6IHtcbiAgICBwb3J0OiA1MTczLFxuICAgIC8vIHNoYXJlZC8gXHU1NzI4IGZyb250ZW5kLyBcdTRFNEJcdTU5MTYsIFx1NTE0MVx1OEJCOCBkZXYgc2VydmVyIFx1OEJGQlx1NTNENlx1NEUwQVx1NEUwMFx1N0VBN1x1NzZFRVx1NUY1NVxuICAgIGZzOiB7IGFsbG93OiBbJy4uJ10gfSxcbiAgICBwcm94eToge1xuICAgICAgJy9hcGknOiB7XG4gICAgICAgIHRhcmdldDogJ2h0dHA6Ly9sb2NhbGhvc3Q6ODAwMCcsXG4gICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZSxcbiAgICAgIH0sXG4gICAgfSxcbiAgfSxcbn0pXG4iXSwKICAibWFwcGluZ3MiOiAiO0FBQ0EsU0FBUyxvQkFBb0I7QUFDN0IsT0FBTyxXQUFXO0FBQ2xCLFNBQVMsZUFBZSxXQUFXO0FBSDZLLElBQU0sMkNBQTJDO0FBS2pRLElBQU8sc0JBQVEsYUFBYTtBQUFBLEVBQzFCLFNBQVMsQ0FBQyxNQUFNLENBQUM7QUFBQSxFQUNqQixNQUFNO0FBQUE7QUFBQSxJQUVKLFNBQVMsQ0FBQyxzQkFBc0Isa0JBQWtCO0FBQUEsSUFDbEQsYUFBYTtBQUFBLEVBQ2Y7QUFBQSxFQUNBLFNBQVM7QUFBQSxJQUNQLE9BQU87QUFBQSxNQUNMLEtBQUssY0FBYyxJQUFJLElBQUksU0FBUyx3Q0FBZSxDQUFDO0FBQUE7QUFBQSxNQUVwRCxXQUFXLGNBQWMsSUFBSSxJQUFJLGFBQWEsd0NBQWUsQ0FBQztBQUFBLElBQ2hFO0FBQUEsRUFDRjtBQUFBLEVBQ0EsT0FBTztBQUFBO0FBQUEsSUFFTCxlQUFlO0FBQUEsTUFDYixRQUFRO0FBQUEsUUFDTixjQUFjO0FBQUEsVUFDWixPQUFPLENBQUMsU0FBUyxhQUFhLGtCQUFrQjtBQUFBLFVBQ2hELE1BQU0sQ0FBQyxRQUFRLG1CQUFtQjtBQUFBLFFBQ3BDO0FBQUEsTUFDRjtBQUFBLElBQ0Y7QUFBQSxJQUNBLHVCQUF1QjtBQUFBLEVBQ3pCO0FBQUEsRUFDQSxRQUFRO0FBQUEsSUFDTixNQUFNO0FBQUE7QUFBQSxJQUVOLElBQUksRUFBRSxPQUFPLENBQUMsSUFBSSxFQUFFO0FBQUEsSUFDcEIsT0FBTztBQUFBLE1BQ0wsUUFBUTtBQUFBLFFBQ04sUUFBUTtBQUFBLFFBQ1IsY0FBYztBQUFBLE1BQ2hCO0FBQUEsSUFDRjtBQUFBLEVBQ0Y7QUFDRixDQUFDOyIsCiAgIm5hbWVzIjogW10KfQo=
