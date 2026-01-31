import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/downloads/ws': {
        target: 'ws://localhost:5172',
        ws: true,
      },
      '/api': {
        target: 'http://localhost:5172',
        changeOrigin: true,
      },
    },
  },
})
