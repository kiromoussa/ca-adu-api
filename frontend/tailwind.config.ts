import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0b1220",
          soft: "#1a2436"
        },
        brand: {
          DEFAULT: "#2563eb",
          dark: "#1d4ed8",
          light: "#3b82f6"
        },
        surface: {
          DEFAULT: "#ffffff",
          muted: "#f6f8fb",
          border: "#e5e9f0"
        }
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif"
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace"
        ]
      }
    }
  },
  plugins: []
};

export default config;
