import type { Config } from 'tailwindcss';
import animate from 'tailwindcss-animate';

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        cream: { DEFAULT: '#f2ead8', light: '#faf6ec', dark: '#e6dcc4' },
        moss: { DEFAULT: '#2d5a27', mid: '#4a7a3e', light: '#6ba35a' },
        ember: { DEFAULT: '#c8501a', light: '#e07040' },
        ink: { DEFAULT: '#1e2a18', muted: '#6b6b50' },
        // shadcn semantic tokens mapped to gateway palette
        background: '#f2ead8',
        foreground: '#1e2a18',
        primary: { DEFAULT: '#2d5a27', foreground: '#faf6ec' },
        secondary: { DEFAULT: '#e6dcc4', foreground: '#1e2a18' },
        accent: { DEFAULT: '#c8501a', foreground: '#ffffff' },
        destructive: { DEFAULT: '#b91c1c', foreground: '#ffffff' },
        border: '#c4b492',
        input: '#c4b492',
        ring: '#2d5a27',
        muted: { DEFAULT: '#e6dcc4', foreground: '#6b6b50' },
        card: { DEFAULT: '#faf6ec', foreground: '#1e2a18' },
        popover: { DEFAULT: '#faf6ec', foreground: '#1e2a18' },
      },
      fontFamily: {
        serif: ['Georgia', '"Times New Roman"', 'serif'],
        mono: ['"Courier New"', 'monospace'],
      },
      borderRadius: {
        lg: '0.5rem',
        md: '0.375rem',
        sm: '0.25rem',
      },
    },
  },
  plugins: [animate],
} satisfies Config;
