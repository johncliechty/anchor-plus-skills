/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx,mjs}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#020617',
        },
      },
      boxShadow: {
        'glow-success': '0 0 15px rgba(52, 211, 153, 0.15)',
        'glow-failure': '0 0 15px rgba(248, 113, 113, 0.15)',
        'glow-info': '0 0 15px rgba(96, 165, 250, 0.15)',
      }
    },
  },
  plugins: [],
}
