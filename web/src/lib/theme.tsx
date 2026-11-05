import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Choice = "system" | "dark" | "light";
type Resolved = "dark" | "light";

const Ctx = createContext<{ choice: Choice; resolved: Resolved; setChoice: (c: Choice) => void }>({
  choice: "system",
  resolved: "dark",
  setChoice: () => {},
});

function read(): Choice {
  try {
    const v = localStorage.getItem("theme");
    return v === "dark" || v === "light" ? v : "system";
  } catch {
    return "system";
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<Choice>(read);
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? true,
  );
  useEffect(() => {
    const m = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!m) return;
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  const resolved: Resolved = choice === "system" ? (systemDark ? "dark" : "light") : choice;
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", resolved === "dark" ? "#0a0c0f" : "#f5f6f8");
  }, [resolved]);
  const value = useMemo(
    () => ({
      choice,
      resolved,
      setChoice: (c: Choice) => {
        setChoiceState(c);
        try {
          localStorage.setItem("theme", c);
        } catch {
          /* private mode */
        }
      },
    }),
    [choice, resolved],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

/** Current token values for canvas charts (they can't read CSS variables themselves). */
export function tokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (name: string) => s.getPropertyValue(name).trim();
  return {
    bg: v("--bg"),
    panel: v("--panel"),
    text: v("--text"),
    muted: v("--muted"),
    faint: v("--faint"),
    border: v("--border"),
    grid: v("--grid"),
    accent: v("--accent"),
    pos: v("--pos"),
    neg: v("--neg"),
    warn: v("--warn"),
    violet: v("--violet"),
  };
}

export const SERIES = [
  "#6ea8ff", "#f2a65a", "#4fd1c5", "#c792ea", "#f07178", "#a5d66b",
  "#ffcb6b", "#82aaff", "#89ddff", "#d4a5ff", "#ff9e64", "#9fb8c9",
];
