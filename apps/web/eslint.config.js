// ---------------------------------------------------------------------------
// WBTimeAI · 前端 ESLint 配置（T0-23 / §2U.2）
//
// ESLint 9 flat config（ESM）。组合：
//   - @eslint/js recommended
//   - typescript-eslint recommended（不含 strict-type-checked 全套）
//   - eslint-plugin-react-hooks recommended
//   - eslint-plugin-react-refresh（仅导出组件告警）
//   - eslint-config-prettier 置于末尾，关闭与 Prettier 冲突的格式规则
// ---------------------------------------------------------------------------
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import prettier from "eslint-config-prettier";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "coverage"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    },
  },
  {
    // shadcn/ui 原语**有意**共导出 cva 变体（badgeVariants / buttonVariants 等），
    // 与 Fast Refresh「仅导出组件」规则冲突；对设计系统原语关闭该规则，避免噪音。
    files: ["src/components/ui/**/*.{ts,tsx}"],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
  {
    files: ["**/*.{js,jsx,mjs,cjs}"],
    extends: [js.configs.recommended],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.node,
    },
  },
  prettier,
);
