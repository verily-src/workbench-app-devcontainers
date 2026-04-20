import axios from 'axios'

export const api = axios.create({
  baseURL: './api/',  // Relative to current page path
  headers: {
    'Content-Type': 'application/json',
  },
})
