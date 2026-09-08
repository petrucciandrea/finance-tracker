import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      // Mirrors the "@/*" path in tsconfig.app.json — both need to agree,
      // TypeScript checks types with its version, Vite resolves imports
      // at build/dev time with this one.
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,       // needed so Vite is reachable from outside the Docker container
    port: 5173,
    watch: {
      usePolling: true, // file-change detection is unreliable on some Docker+OS combos otherwise
    },
  },
})
