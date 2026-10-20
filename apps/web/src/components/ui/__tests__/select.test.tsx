// ---------------------------------------------------------------------------
// D-UI 体验优化波 · WS-F · Select 原语键盘可达断言（DU-5）
//
// 覆盖：触发器语义（combobox）、占位文案、键盘展开（ArrowDown）与
// 键盘选中（ArrowDown + Enter）。jsdom 缺失的指针/滚动 API 在此补齐。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

beforeAll(() => {
  const proto = Element.prototype as Element & {
    hasPointerCapture?: (pointerId: number) => boolean;
    setPointerCapture?: (pointerId: number) => void;
    releasePointerCapture?: (pointerId: number) => void;
  };
  if (typeof proto.hasPointerCapture !== "function") {
    proto.hasPointerCapture = () => false;
  }
  if (typeof proto.setPointerCapture !== "function") {
    proto.setPointerCapture = () => {};
  }
  if (typeof proto.releasePointerCapture !== "function") {
    proto.releasePointerCapture = () => {};
  }
  if (typeof HTMLElement.prototype.scrollIntoView !== "function") {
    HTMLElement.prototype.scrollIntoView = () => {};
  }
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    } as unknown as typeof ResizeObserver;
  }
});

describe("Select（原语 · DU-5）", () => {
  it("触发器具备 combobox 语义并渲染占位文案", () => {
    render(
      <Select>
        <SelectTrigger data-testid="demo-select">
          <SelectValue placeholder="请选择" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="alpha">Alpha</SelectItem>
          <SelectItem value="beta">Beta</SelectItem>
        </SelectContent>
      </Select>,
    );

    const trigger = screen.getByTestId("demo-select");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAttribute("role", "combobox");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("请选择")).toBeInTheDocument();
  });

  it("键盘可达：ArrowDown 展开、ArrowDown + Enter 选中", async () => {
    const onValueChange = vi.fn();
    render(
      <Select onValueChange={onValueChange}>
        <SelectTrigger data-testid="kbd-select">
          <SelectValue placeholder="请选择" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="alpha">Alpha</SelectItem>
          <SelectItem value="beta">Beta</SelectItem>
          <SelectItem value="gamma">Gamma</SelectItem>
        </SelectContent>
      </Select>,
    );

    const trigger = screen.getByTestId("kbd-select");
    trigger.focus();
    expect(trigger).toHaveFocus();

    // 键盘展开。
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "true"));
    await screen.findByText("Alpha");

    // 键盘下移高亮首项 + 确认（radix：展开后用 ArrowDown 高亮首个可选项）。
    const active = document.activeElement as HTMLElement;
    fireEvent.keyDown(active, { key: "ArrowDown" });
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Enter" });

    await waitFor(() => expect(onValueChange).toHaveBeenCalledTimes(1));
    expect(onValueChange).toHaveBeenCalledWith("alpha");
  });

  it("键盘 Esc 关闭浮层", async () => {
    render(
      <Select>
        <SelectTrigger data-testid="esc-select">
          <SelectValue placeholder="请选择" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="alpha">Alpha</SelectItem>
        </SelectContent>
      </Select>,
    );

    const trigger = screen.getByTestId("esc-select");
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "true"));

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-expanded", "false"));
  });
});
