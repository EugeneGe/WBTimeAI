import type { Config } from "tailwindcss";

/**
 * Tailwind 配置（shadcn/ui 风格：CSS 变量主题 token；`darkMode: "class"`）。
 *
 * D-UI 体验优化波 · WS-F：
 * - 新增语义色 `page` / `success` / `warning`（§4.2 冻结名，消费侧只引用）；
 * - 其余结构不变，仅随 `index.css` 的 CSS 变量值变色；
 * - 字号阶梯收口：`text-xs=12` / `text-sm=13`（正文）→ 见 `extend.fontSize`。
 */
const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        /* 页面底色（最外层基调，§4.2 固化名） */
        page: "hsl(var(--page))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        /* 语义色新增（§4.2） */
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      /* 字号阶梯（§4.1）：12 辅助 / 13 正文 / 15 标题 / 20 空态问候 */
      fontSize: {
        xs: ["12px", { lineHeight: "1.5" }],
        sm: ["13px", { lineHeight: "1.5" }],
        base: ["13px", { lineHeight: "1.6" }],
        title: ["15px", { lineHeight: "1.4" }],
        greeting: ["20px", { lineHeight: "1.3" }],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
