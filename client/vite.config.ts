import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the Vite server proxies the API (and WebSocket) to the Command Server
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    proxy: {
      '/api': { target: 'http://localhost:8000', ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 4000 },
})
