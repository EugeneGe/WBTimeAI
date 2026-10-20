// ---------------------------------------------------------------------------
// WBTimeAI · 设置·通用「通知提示音 · 自定义」单测（V0.4.6 BugFix · B-05）
//
// 覆盖：选中「自定义」出现导入行 / 导入音频后显示文件名并落 localStorage /
// 非法类型与超限文件被拒绝并 toast。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { GeneralSection } from "@/components/settings/sections/GeneralSection";
import { CUSTOM_SOUND_MAX_BYTES } from "@/lib/notifySound";
import { useI18nStore } from "@/stores/i18nStore";
import { useUiStore } from "@/stores/uiStore";

/** 预置「自定义」选择，直接渲染出导入行。 */
function presetCustomChoice(): void {
  window.localStorage.setItem("wbtime-ai.notify-sound.choice", "custom");
}

// jsdom 未实现 scrollIntoView；Radix Select 打开时会调用（否则抛未处理异常）。
if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = () => undefined;
}

describe("GeneralSection · 通知提示音自定义（B-05）", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useI18nStore.setState({ language: "zh-CN" });
    useUiStore.setState({ toast: null });
  });

  it("下拉含「自定义」；选中后出现导入行（未选文件时提示空态）", async () => {
    render(<GeneralSection />);

    const trigger = screen.getByTestId("settings-notification-sound");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });

    const option = await screen.findByRole("option", { name: "自定义" });
    fireEvent.click(option);

    expect(await screen.findByTestId("settings-notification-sound-custom")).toBeInTheDocument();
    expect(screen.getByTestId("settings-notification-sound-custom-name")).toHaveTextContent(
      "未选择音效文件",
    );
    expect(screen.getByTestId("settings-notification-sound-custom-preview")).toBeDisabled();
    expect(window.localStorage.getItem("wbtime-ai.notify-sound.choice")).toBe("custom");
  });

  it("导入音频：显示文件名、持久化 data URL、试听按钮可用", async () => {
    presetCustomChoice();
    render(<GeneralSection />);

    const file = new File([new Uint8Array([1, 2, 3])], "ding.mp3", { type: "audio/mpeg" });
    fireEvent.change(screen.getByTestId("settings-notification-sound-custom-file"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(screen.getByTestId("settings-notification-sound-custom-name")).toHaveTextContent(
        "ding.mp3",
      );
    });
    expect(screen.getByTestId("settings-notification-sound-custom-preview")).toBeEnabled();

    const stored = window.localStorage.getItem("wbtime-ai.notify-sound.custom");
    expect(stored).not.toBeNull();
    expect(JSON.parse(stored ?? "{}")).toMatchObject({
      name: "ding.mp3",
      dataUrl: expect.stringMatching(/^data:audio\/mpeg;base64,/),
    });
  });

  it("非音频文件被拒绝并 toast", async () => {
    presetCustomChoice();
    render(<GeneralSection />);

    const file = new File(["hello"], "note.txt", { type: "text/plain" });
    fireEvent.change(screen.getByTestId("settings-notification-sound-custom-file"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(useUiStore.getState().toast?.title).toBe("无法导入音效");
    });
    expect(useUiStore.getState().toast?.description).toBe("请选择音频文件");
    expect(window.localStorage.getItem("wbtime-ai.notify-sound.custom")).toBeNull();
  });

  it("超过 1 MB 的音频被拒绝并 toast", async () => {
    presetCustomChoice();
    render(<GeneralSection />);

    const file = new File([new Uint8Array(CUSTOM_SOUND_MAX_BYTES + 1)], "big.mp3", {
      type: "audio/mpeg",
    });
    fireEvent.change(screen.getByTestId("settings-notification-sound-custom-file"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(useUiStore.getState().toast?.description).toBe("音效文件不能超过 1 MB");
    });
    expect(window.localStorage.getItem("wbtime-ai.notify-sound.custom")).toBeNull();
  });
});
