// ---------------------------------------------------------------------------
// WBTimeAI · 通知提示音偏好（B-05，V0.4.6 BugFix）
//
// 背景：设置·通用「通知提示音」原为 UI 占位（dynamic/crisp/mute），本波新增
// 「自定义」并允许导入本地音效。
//
// 存储口径（纯前端，无需后端 / 壳 IPC）：
// - 选择值：`localStorage["wbtime-ai.notify-sound.choice"]`；
// - 自定义音效：`localStorage["wbtime-ai.notify-sound.custom"]`（`{ name, dataUrl }` JSON）。
//   - 以 **data URL** 保存，Web 与桌面壳（同一 renderer origin）均可复现；
//   - 上限 {@link CUSTOM_SOUND_MAX_BYTES}（1 MB）：localStorage 配额约 5 MB，留足余量；
//   - 读写均 try/catch：隐私模式 / 配额不足时**不抛异常**，由调用方提示。
//
// 🔴 只做「偏好与试听」，任务完成时的真实播放仍待通知能力接入（原占位语义不变）。
// ---------------------------------------------------------------------------

/** 可选提示音：内置三项 + 自定义。 */
export type NotifySoundChoice = "dynamic" | "crisp" | "mute" | "custom";

/** 自定义音效（文件名 + data URL）。 */
export interface CustomNotifySound {
  name: string;
  dataUrl: string;
}

/** 自定义音效体积上限（1 MB）。 */
export const CUSTOM_SOUND_MAX_BYTES = 1024 * 1024;

const CHOICE_KEY = "wbtime-ai.notify-sound.choice";
const CUSTOM_KEY = "wbtime-ai.notify-sound.custom";

/** 类型守卫：`value` 是否为合法提示音选项。 */
export function isNotifySoundChoice(value: unknown): value is NotifySoundChoice {
  return value === "dynamic" || value === "crisp" || value === "mute" || value === "custom";
}

/** 读取提示音选择（缺省 `dynamic`，与既有默认一致）。 */
export function loadNotifySoundChoice(): NotifySoundChoice {
  try {
    const stored = window.localStorage.getItem(CHOICE_KEY);
    return isNotifySoundChoice(stored) ? stored : "dynamic";
  } catch {
    return "dynamic";
  }
}

/** 保存提示音选择（失败静默：偏好丢失优于抛错）。 */
export function saveNotifySoundChoice(choice: NotifySoundChoice): void {
  try {
    window.localStorage.setItem(CHOICE_KEY, choice);
  } catch {
    // 忽略存储异常。
  }
}

/** 读取自定义音效（缺失 / 结构非法 → `null`）。 */
export function loadCustomNotifySound(): CustomNotifySound | null {
  try {
    const raw = window.localStorage.getItem(CUSTOM_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<CustomNotifySound> | null;
    if (
      parsed &&
      typeof parsed.name === "string" &&
      parsed.name.length > 0 &&
      typeof parsed.dataUrl === "string" &&
      parsed.dataUrl.startsWith("data:audio/")
    ) {
      return { name: parsed.name, dataUrl: parsed.dataUrl };
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 保存自定义音效。
 *
 * @returns `true` = 已写入；`false` = 存储失败（配额 / 隐私模式）。
 */
export function saveCustomNotifySound(sound: CustomNotifySound): boolean {
  try {
    window.localStorage.setItem(CUSTOM_KEY, JSON.stringify(sound));
    return true;
  } catch {
    return false;
  }
}

/** 清除自定义音效（选择值不动）。 */
export function clearCustomNotifySound(): void {
  try {
    window.localStorage.removeItem(CUSTOM_KEY);
  } catch {
    // 忽略存储异常。
  }
}

/** 校验结果：`ok` 或错误码（供调用方映射 i18n 文案）。 */
export type AudioFileCheck = { ok: true } | { ok: false; reason: "type" | "size" | "read" };

/** 校验所选文件是否为可用的音频（类型 / 体积）。 */
export function checkAudioFile(file: File): AudioFileCheck {
  if (!file.type.startsWith("audio/")) {
    return { ok: false, reason: "type" };
  }
  if (file.size > CUSTOM_SOUND_MAX_BYTES) {
    return { ok: false, reason: "size" };
  }
  return { ok: true };
}

/** 读取音频文件为 data URL（失败 → `null`）。 */
export function readAudioFile(file: File): Promise<string | null> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve(typeof reader.result === "string" ? reader.result : null);
    };
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(file);
  });
}
