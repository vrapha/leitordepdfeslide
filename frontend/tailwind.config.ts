import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        emr: {
          green: '#1a7a3e',
          'green-light': '#22a052',
          'green-dark': '#125c2d',
          red: '#c0392b',
        },
      },
    },
  },
  plugins: [],
} satisfies Config
