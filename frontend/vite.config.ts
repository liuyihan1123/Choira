import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发时前端跑 5173，/api 代理到后端 8000；构建产物由后端直接托管。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1600,
  },
})
