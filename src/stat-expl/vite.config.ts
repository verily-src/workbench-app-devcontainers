import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',  // Relative paths for Workbench proxy
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
