// tailwind.config.js — Tailwind setup, ported from raggles.
// Theme colors are CSS variables (see index.css) so dark/light mode is a
// single class flip on <html> rather than duplicated utility classes.
/** @type {import('tailwindcss').Config} */
export default {
  // Scan the entry HTML and all source files for used utility classes.
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  // Dark mode is driven by the .dark class (toggled by the theme switcher).
  darkMode: 'class',
  theme: {
    extend: {
      // Map semantic color names onto the CSS variables.
      colors: {
        theme: {
          base: 'var(--bg-base)',
          surface: 'var(--bg-surface)',
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          tertiary: 'var(--text-tertiary)',
          accent: 'var(--accent)',
          'accent-hover': 'var(--accent-hover)',
        },
      },
      borderColor: {
        theme: {
          main: 'var(--border-main)',
          subtle: 'var(--border-subtle)',
        },
      },
    },
  },
  plugins: [],
}
