import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',  // Relative paths for Workbench proxy
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
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
