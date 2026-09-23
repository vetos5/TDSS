import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// Backend URL for the dev proxy; override with TDSS_API=http://localhost:8060 npm run dev
const apiTarget = process.env.TDSS_API ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: true,
    proxy: {
      '/api': apiTarget,
      '/blueprints': apiTarget,
    },
  },
})
