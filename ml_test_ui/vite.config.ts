import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    include: ['react-is']
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/health':  'http://localhost:8000',
      '/api':     'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
      '/output':  'http://localhost:8000',
    },
  },
})
