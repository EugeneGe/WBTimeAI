// ---------------------------------------------------------------------------
// 桌面壳动作调用帮助（V0.4.5 B5 · F-25 / F-26.5）
//
// 镜像 T01 侧 IPC 契约 `window.wbtimeAiDesktop.shellAction(payload)`：
// - 壳内可用（invoke）；纯 Web 环境为 `undefined`；
// - 消费侧一律经 {@link hasShellAction} 判定可用性、经 {@link invokeShellAction} 调用；
// - 🔴 不修改 `types/desktop.d.ts`（T01 独占写权），此处以局部类型断言对齐契约。
// ---------------------------------------------------------------------------

/** shellAction 支持的动作载荷（与 T01 契约逐字对齐）。 */
export type ShellActionPayload =
  | {
      action: "open-settings";
      section?:
        "profile" | "general" | "appearance" | "shortcuts" | "models" | "system" | "about" | "help";
    }
  | { action: "restart-backend" }
  | { action: "show-guide" }
  | { action: "about" }
  | { action: "zoom"; mode: "in" | "out" | "reset" };

/** 壳动作函数类型（局部断言形状）。 */
type ShellActionFn = (payload: ShellActionPayload) => unknown;

/** 读取壳动作函数（纯 Web 环境 → `undefined`）。 */
function getShellAction(): ShellActionFn | undefined {
  const shell = (window as unknown as { wbtimeAiDesktop?: { shellAction?: ShellActionFn } })
    .wbtimeAiDesktop;
  return shell?.shellAction;
}

/** 当前是否运行于带 shellAction 的桌面壳内。 */
export function hasShellAction(): boolean {
  return typeof getShellAction() === "function";
}

/** 调用壳动作（壳内执行；纯 Web 环境静默忽略）。 */
export function invokeShellAction(payload: ShellActionPayload): void {
  const action = getShellAction();
  if (typeof action === "function") {
    void action(payload);
  }
}
