import axios from 'axios'

export const api = axios.create({
  baseURL: './dashboard/api/',  // Workbench reserves /api/, use custom prefix
  headers: {
    'Content-Type': 'application/json',
  },
})
