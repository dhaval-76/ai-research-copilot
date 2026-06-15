/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0F1115",
        surface: "#1A1D24",
        surface2: "#21252E",
        border: "#2A2E38",
        text: "#E6E8EC",
        muted: "#8A93A6",
        accent: "#5EEAD4",
        warning: "#F5A623",
        danger: "#F87171",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};