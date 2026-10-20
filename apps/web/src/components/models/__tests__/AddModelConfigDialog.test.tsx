// ---------------------------------------------------------------------------
// WBTimeAI · 「添加模型配置」弹窗单测（V0.4.6 BugFix · B-07）
//
// 覆盖：常用/自定义表单切换、必填校验、两条保存链路（Provider → 凭证 → 绑定 → 模型）。
// ---------------------------------------------------------------------------
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddModelConfigDialog } from "@/components/models/AddModelConfigDialog";
import { useI18nStore } from "@/stores/i18nStore";

const modelSpy = vi.hoisted(() => ({
  providers: [] as Array<{ id: string; name: string; type?: string; config?: unknown }>,
  registerProvider: vi.fn(),
  registerModel: vi.fn(),
  saveCredential: vi.fn(),
  bindCredential: vi.fn(),
}));

vi.mock("@/hooks/useModels", () => ({
  useProviders: () => ({ data: modelSpy.providers }),
  useRegisterProvider: () => ({ mutateAsync: modelSpy.registerProvider, isPending: false }),
  useRegisterModel: () => ({ mutateAsync: modelSpy.registerModel, isPending: false }),
  useSaveCredential: () => ({ mutateAsync: modelSpy.saveCredential, isPending: false }),
  useBindCredential: () => ({ mutateAsync: modelSpy.bindCredential, isPending: false }),
}));

describe("AddModelConfigDialog · B-07", () => {
  const onOpenChange = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    useI18nStore.setState({ language: "zh-CN" });
    modelSpy.providers = [];
    modelSpy.registerProvider.mockResolvedValue({ id: "p1", name: "OpenAI", type: "openai" });
    modelSpy.saveCredential.mockResolvedValue({ id: "c1", masked_value: "sk-…" });
    modelSpy.bindCredential.mockResolvedValue({ id: "p1" });
    modelSpy.registerModel.mockResolvedValue({ id: "m1", name: "gpt-4o" });
  });

  it("默认常用模型：提供方 + 预设模型；缺 API Key 时拦截提交", async () => {
    render(<AddModelConfigDialog open onOpenChange={onOpenChange} />);

    expect(screen.getByTestId("add-model-kind-common")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("add-model-preset")).toBeInTheDocument();
    expect(screen.getByTestId("add-model-common-name")).toHaveTextContent("gpt-4o");

    fireEvent.click(screen.getByTestId("add-model-submit"));

    expect(await screen.findByTestId("add-model-error")).toHaveTextContent("请填写 API Key");
    expect(modelSpy.registerProvider).not.toHaveBeenCalled();
  });

  it("自定义模型：显示 Base URL / 模型名 / 上下文窗口；缺 Base URL 时拦截提交", async () => {
    render(<AddModelConfigDialog open onOpenChange={onOpenChange} />);

    fireEvent.click(screen.getByTestId("add-model-kind-custom"));
    expect(screen.getByTestId("add-model-kind-custom")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("add-model-endpoint")).toBeInTheDocument();
    expect(screen.getByTestId("add-model-name")).toBeInTheDocument();
    expect(screen.getByTestId("add-model-context")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("add-model-submit"));

    expect(await screen.findByTestId("add-model-error")).toHaveTextContent("请填写 Base URL");
    expect(modelSpy.registerProvider).not.toHaveBeenCalled();
  });

  it("常用模型保存：建 Provider → 存凭证 → 绑定 → 注册模型，并关闭弹窗", async () => {
    render(<AddModelConfigDialog open onOpenChange={onOpenChange} />);
    fireEvent.change(screen.getByTestId("add-model-api-key"), {
      target: { value: "sk-test-123" },
    });

    fireEvent.click(screen.getByTestId("add-model-submit"));

    await waitFor(() => {
      expect(modelSpy.registerModel).toHaveBeenCalledTimes(1);
    });

    expect(modelSpy.registerProvider).toHaveBeenCalledWith({
      name: "OpenAI",
      provider_type: "openai",
      endpoint: "https://api.openai.com/v1",
      config: { model_kind: "common", preset: "openai" },
    });
    expect(modelSpy.saveCredential).toHaveBeenCalledWith({
      provider: "OpenAI",
      key_type: "api_key",
      value: "sk-test-123",
    });
    expect(modelSpy.bindCredential).toHaveBeenCalledWith({
      providerId: "p1",
      payload: { credential_id: "c1" },
    });
    expect(modelSpy.registerModel).toHaveBeenCalledWith({
      providerId: "p1",
      payload: { name: "gpt-4o", model_type: "CHAT", context_window: null },
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("自定义模型保存：openai_compatible + model_kind=custom，上下文窗口写入", async () => {
    render(<AddModelConfigDialog open onOpenChange={onOpenChange} />);

    fireEvent.click(screen.getByTestId("add-model-kind-custom"));
    fireEvent.change(screen.getByTestId("add-model-provider-name"), {
      target: { value: "内部网关" },
    });
    fireEvent.change(screen.getByTestId("add-model-endpoint"), {
      target: { value: "https://llm.internal/v1" },
    });
    fireEvent.change(screen.getByTestId("add-model-name"), {
      target: { value: "inhouse-7b" },
    });
    fireEvent.change(screen.getByTestId("add-model-context"), {
      target: { value: "128000" },
    });

    fireEvent.click(screen.getByTestId("add-model-submit"));

    await waitFor(() => {
      expect(modelSpy.registerModel).toHaveBeenCalledTimes(1);
    });

    expect(modelSpy.registerProvider).toHaveBeenCalledWith({
      name: "内部网关",
      provider_type: "openai_compatible",
      endpoint: "https://llm.internal/v1",
      config: { model_kind: "custom" },
    });
    // 未填 API Key → 不创建凭证、不绑定。
    expect(modelSpy.saveCredential).not.toHaveBeenCalled();
    expect(modelSpy.bindCredential).not.toHaveBeenCalled();
    expect(modelSpy.registerModel).toHaveBeenCalledWith({
      providerId: "p1",
      payload: { name: "inhouse-7b", model_type: "CHAT", context_window: 128000 },
    });
  });
});
