import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend configuration from environment or defaults
const BACKEND_HOST = process.env.VITE_BACKEND_HOST || '127.0.0.1'
const BACKEND_PORT = process.env.VITE_BACKEND_PORT || '5050'
const FRONTEND_PORT = process.env.VITE_PORT || 3000

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // Listen on all network interfaces
    port: Number(FRONTEND_PORT),
    proxy: {
      '/api': {
        target: `http://${BACKEND_HOST}:${BACKEND_PORT}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
