import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './',  // Relative paths for Workbench proxy
  server: {
    port: 8080,
    host: '0.0.0.0',
    allowedHosts: [
      '.workbench-app-prod.verily.com',
      '.workbench-app.verily.com',
      'localhost'
    ]
  }
})
