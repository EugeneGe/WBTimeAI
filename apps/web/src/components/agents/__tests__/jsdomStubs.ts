// ---------------------------------------------------------------------------
// WBTimeAI · agents 目录测试公共桩（B-15）
//
// jsdom 缺 radix（tabs / dialog / dropdown-menu / floating-ui）所需的最小实现，
// 各测试文件挂载含 Dialog / Tabs 的组件前调用 {@link installRadixStubs}
// （对齐 `Agents.test.tsx` 内联桩范式，抽出复用避免三份拷贝漂移）。
// ---------------------------------------------------------------------------

/** 安装 radix 所需的最小 jsdom 桩（幂等）。 */
export function installRadixStubs(): void {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe(): void {
        void 0;
      }
      unobserve(): void {
        void 0;
      }
      disconnect(): void {
        void 0;
      }
    } as unknown as typeof ResizeObserver;
  }
  if (typeof window.PointerEvent === "undefined") {
    window.PointerEvent = MouseEvent as unknown as typeof PointerEvent;
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = (): void => {
      void 0;
    };
  }
  if (!Element.prototype.hasPointerCapture) {
    Element.prototype.hasPointerCapture = (): boolean => false;
  }
  if (!Element.prototype.setPointerCapture) {
    Element.prototype.setPointerCapture = (): void => {
      void 0;
    };
  }
  if (!Element.prototype.releasePointerCapture) {
    Element.prototype.releasePointerCapture = (): void => {
      void 0;
    };
  }
}
