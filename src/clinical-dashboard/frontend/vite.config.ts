import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',  // Relative paths for Workbench proxy
  resolve: {
    alias: {
      // Polyfill Node.js modules for browser (plotly.js needs these)
      buffer: 'buffer/',
      stream: 'stream-browserify',
      util: 'util/',
    },
  },
  define: {
    // Define global for browser compatibility
    global: 'globalThis',
    'process.env': {},
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
})
