import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 构建产物直接进 Python 包，pip 安装即带前端，无需 Node
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../src/ai_workflow_gui/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
})
