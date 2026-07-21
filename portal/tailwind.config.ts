import type { Config } from "tailwindcss";

// Colors are driven by CSS custom properties (see globals.css) defined as
// space-separated RGB channels, so a single set of utility classes themes for
// both light and dark and still supports Tailwind opacity modifiers
// (e.g. text-ink/60). "canvas" is kept as an alias for "paper" for safety.
const withVar = (v: string) => `rgb(var(${v}) / <alpha-value>)`;

const config: Config = {
  darkMode: "media",
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: withVar("--paper"),
        canvas: withVar("--paper"),
        surface: withVar("--surface"),
        "surface-2": withVar("--surface-2"),
        ink: withVar("--ink"),
        muted: withVar("--muted"),
        faint: withVar("--faint"),
        line: withVar("--line"),
        "line-strong": withVar("--line-strong"),
        accent: withVar("--accent"),
        "accent-deep": withVar("--accent-deep"),
        ok: withVar("--ok"),
        warn: withVar("--warn"),
        review: withVar("--review"),
      },
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "SF Mono",
          "Menlo",
          "Consolas",
          "Liberation Mono",
          "monospace",
        ],
      },
      maxWidth: {
        content: "72rem",
        measure: "65ch",
      },
      letterSpacing: {
        tightest: "-0.03em",
      },
      borderRadius: {
        card: "8px",
      },
    },
  },
  plugins: [],
};

export default config;
