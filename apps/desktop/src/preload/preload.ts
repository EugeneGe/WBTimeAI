// ---------------------------------------------------------------------------
// 预加载脚本（M2 · WS3 · T-02）
//
// 以 `contextBridge` 暴露**最小受控** API 到渲染层（`window.astraDesktop`）。
// 🔴 `sandbox:true` 下预加载无完整 Node：本文件**仅**引用 `electron` 运行时 +
//    `import type`（编译期擦除）——**不得**引入任何运行期第三方 / Node 模块。
// ---------------------------------------------------------------------------
import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import type {
  AstraDesktopApi,
  BackendStatus,
  DesktopSettings,
  DesktopSettingsPatch,
} from "../shared/protocol";

const CHANNELS = {
  status: "backend:status",
  setRemote: "backend:setRemote",
  restart: "backend:restart",
  getSettings: "settings:get",
  setSettings: "settings:set",
  statusChanged: "backend:status-changed",
} as const;

const api: AstraDesktopApi = {
  getStatus: (): Promise<BackendStatus> => ipcRenderer.invoke(CHANNELS.status),

  setRemote: (baseUrl: string): Promise<BackendStatus> =>
    ipcRenderer.invoke(CHANNELS.setRemote, baseUrl),

  restartBackend: (): Promise<BackendStatus> => ipcRenderer.invoke(CHANNELS.restart),

  getSettings: (): Promise<DesktopSettings> => ipcRenderer.invoke(CHANNELS.getSettings),

  setSettings: (patch: DesktopSettingsPatch): Promise<DesktopSettings> =>
    ipcRenderer.invoke(CHANNELS.setSettings, patch),

  onStatus: (listener: (status: BackendStatus) => void): (() => void) => {
    const handler = (_event: IpcRendererEvent, status: BackendStatus): void => listener(status);
    ipcRenderer.on(CHANNELS.statusChanged, handler);
    return () => {
      ipcRenderer.removeListener(CHANNELS.statusChanged, handler);
    };
  },
};

contextBridge.exposeInMainWorld("astraDesktop", api);
