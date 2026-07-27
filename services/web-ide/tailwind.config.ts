import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        console: {
          bg: '#f8f9fa',
          surface: '#ffffff',
          border: '#dadce0',
          'border-strong': '#c4c7c5',
          ink: '#202124',
          muted: '#5f6368',
          faint: '#80868b',
          blue: '#1a73e8',
          'blue-hover': '#1765cc',
          'blue-soft': '#e8f0fe',
          'blue-ink': '#174ea6',
          success: '#137333',
          'success-soft': '#e6f4ea',
          danger: '#c5221f',
          'danger-soft': '#fce8e6',
          warn: '#b06000',
          'warn-soft': '#fef7e0',
        },
      },
      boxShadow: {
        console: '0 1px 2px 0 rgba(60,64,67,.3), 0 1px 3px 1px rgba(60,64,67,.15)',
        'console-sm': '0 1px 2px rgba(60,64,67,.3)',
      },
      fontFamily: {
        sans: [
          'var(--font-console)',
          'var(--font-console-zh)',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
    },
  },
  plugins: [],
}

export default config
