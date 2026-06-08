import type { Config } from "tailwindcss";

// Every color is a CSS variable (see globals.css) so light/dark is a class flip
// with no hardcoded colors anywhere in components.
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        border: "var(--border)",
        fg: "var(--fg)",
        muted: "var(--muted)",
        accent: "var(--accent)",
        "accent-fg": "var(--accent-fg)",
        spine: "var(--spine)",
        "node-bg": "var(--node-bg)",
        warn: "var(--warn)",
        overlay: "var(--overlay)",
      },
    },
  },
  plugins: [],
};

export default config;
