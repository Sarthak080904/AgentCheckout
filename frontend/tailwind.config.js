/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: "#7C3AED", foreground: "#FFFFFF" },
        secondary: { DEFAULT: "#A78BFA", foreground: "#0F172A" },
        accent: { DEFAULT: "#0891B2", foreground: "#FFFFFF" },
        background: "#FAF5FF",
        foreground: "#1E1B4B",
        card: { DEFAULT: "#FFFFFF", foreground: "#1E1B4B" },
        muted: { DEFAULT: "#ECEEF9", foreground: "#475569" },
        border: "#DDD6FE",
        destructive: { DEFAULT: "#DC2626", foreground: "#FFFFFF" },
        ring: "#7C3AED",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
