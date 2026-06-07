"use client";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const isDark = theme === "dark";
  return (
    <button
      type="button"
      aria-label="Toggle theme"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg hover:bg-surface-2"
    >
      {mounted ? (isDark ? "☀ Light" : "☾ Dark") : "Theme"}
    </button>
  );
}
