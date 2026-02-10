import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4178,
    proxy: {
      '/api/downloads/ws': {
        target: 'ws://localhost:4177',
        ws: true,
      },
      '/api': {
        target: 'http://localhost:4177',
        changeOrigin: true,
      },
    },
  },
})
