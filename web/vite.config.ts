import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true, // 允许局域网手机访问
    proxy: {
      '/api': {
        // 后端固定 8001（避免与本机残留的 8000 服务冲突）
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
