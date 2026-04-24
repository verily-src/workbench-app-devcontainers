import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Workbench proxy serves the app at a sub-path like
// https://workbench.verily.com/app/<UUID>/proxy/8080/. All assets and API calls
// MUST use relative paths. `base: './'` emits relative URLs in the bundle.
export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: {
      buffer: 'buffer/',
      stream: 'stream-browserify',
      util: 'util/',
    },
  },
  define: {
    global: 'globalThis',
    'process.env': {},
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    allowedHosts: [
      '.workbench-app-prod.verily.com',
      '.workbench-app.verily.com',
      'localhost'
    ]
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
