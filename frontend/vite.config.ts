// vite.config.ts — build/dev-server config for the ragline frontend.
// Ported from raggles unchanged: React plugin + a dev proxy so the Vite dev
// server (:5173) forwards /api requests to the FastAPI backend (:8000).
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // React fast-refresh + JSX transform.
  plugins: [react()],
  server: {
    // In dev, API calls hit the same relative /api paths as production.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
