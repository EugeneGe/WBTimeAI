// ---------------------------------------------------------------------------
// WBTimeAI · 通知提示音偏好单测（V0.4.6 BugFix · B-05）
//
// 覆盖：选择值持久化 / 自定义音效读写与结构校验 / 文件类型与体积校验。
// ---------------------------------------------------------------------------
import { beforeEach, describe, expect, it } from "vitest";

import {
  CUSTOM_SOUND_MAX_BYTES,
  checkAudioFile,
  clearCustomNotifySound,
  isNotifySoundChoice,
  loadCustomNotifySound,
  loadNotifySoundChoice,
  saveCustomNotifySound,
  saveNotifySoundChoice,
} from "@/lib/notifySound";

/** 合法自定义音效样本（data URL 前缀必须是 `data:audio/`）。 */
const SOUND = { name: "ding.mp3", dataUrl: "data:audio/mpeg;base64,AAAA" };

describe("notifySound · B-05", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("选择值缺省为 dynamic，可保存并读回", () => {
    expect(loadNotifySoundChoice()).toBe("dynamic");

    saveNotifySoundChoice("custom");
    expect(loadNotifySoundChoice()).toBe("custom");
    expect(window.localStorage.getItem("wbtime-ai.notify-sound.choice")).toBe("custom");
  });

  it("非法 / 缺失的选择值回退 dynamic", () => {
    window.localStorage.setItem("wbtime-ai.notify-sound.choice", "bogus");
    expect(loadNotifySoundChoice()).toBe("dynamic");
    expect(isNotifySoundChoice("bogus")).toBe(false);
    expect(isNotifySoundChoice("custom")).toBe(true);
  });

  it("自定义音效可保存并读回；结构非法 → null", () => {
    expect(loadCustomNotifySound()).toBeNull();

    expect(saveCustomNotifySound(SOUND)).toBe(true);
    expect(loadCustomNotifySound()).toEqual(SOUND);

    window.localStorage.setItem("wbtime-ai.notify-sound.custom", "{oops");
    expect(loadCustomNotifySound()).toBeNull();

    window.localStorage.setItem(
      "wbtime-ai.notify-sound.custom",
      JSON.stringify({ name: "x", dataUrl: "data:text/plain;base64,AAAA" }),
    );
    expect(loadCustomNotifySound()).toBeNull();
  });

  it("清除自定义音效只删文件、不动选择值", () => {
    saveNotifySoundChoice("custom");
    saveCustomNotifySound(SOUND);

    clearCustomNotifySound();

    expect(loadCustomNotifySound()).toBeNull();
    expect(loadNotifySoundChoice()).toBe("custom");
  });

  it("文件校验：音频通过 / 非音频拒绝 / 超 1 MB 拒绝", () => {
    const ok = new File([new Uint8Array([1, 2, 3])], "ding.mp3", { type: "audio/mpeg" });
    expect(checkAudioFile(ok)).toEqual({ ok: true });

    const wrongType = new File(["hello"], "note.txt", { type: "text/plain" });
    expect(checkAudioFile(wrongType)).toEqual({ ok: false, reason: "type" });

    const tooLarge = new File([new Uint8Array(CUSTOM_SOUND_MAX_BYTES + 1)], "big.mp3", {
      type: "audio/mpeg",
    });
    expect(checkAudioFile(tooLarge)).toEqual({ ok: false, reason: "size" });
  });
});
