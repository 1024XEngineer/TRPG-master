/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        page: '#faf7f0',
        panel: '#f5f0e6',
        card: '#ffffff',
        input: '#fefdfa',
        'border-light': '#e5ded0',
        'border-mid': '#d4cbb8',
        brass: '#b8976a',
        'brass-dark': '#8a6d40',
        rust: '#c04040',
        mold: '#4a8a4a',
        'ink-blue': '#4a7098',
        text: {
          primary: '#2c2416',
          body: '#3d3628',
          muted: '#8a8276',
          dim: '#b0a898'
        }
      },
      borderRadius: {
        sm: '6px',
        md: '10px'
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          '"Helvetica Neue"',
          'sans-serif'
        ],
        mono: ['"Courier New"', '"SF Mono"', 'monospace']
      },
      maxWidth: {
        phone: '390px'
      }
    }
  },
  plugins: []
};
