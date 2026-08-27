import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Same override as api.ts's BACKEND_ORIGIN -- set VITE_BACKEND_ORIGIN in
  // frontend/.env.local to proxy /api to a deployed backend instead of a
  // local one.
  const backendOrigin = env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/api': {
          target: backendOrigin,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
