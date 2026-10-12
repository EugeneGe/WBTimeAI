#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 在 Linux + Docker 宿主上产出 Linux 桌面安装包（M2 · WS3 · T-05）
#
# 背景：本机（Windows）**不能**交叉出 Linux 包（无 Docker/WSL；`service.electron.build`
# 已停）。故本脚本封装 `electronuserland/builder` 容器，在 Linux 服务器（如内网
# `192.168.1.3`）上执行。
#
# 用法（在仓库根或任意位置）：
#   bash apps/desktop/scripts/build-linux-docker.sh
#
# 产物：apps/desktop/release/Astra-AI-<v>.AppImage  +  astra-ai_<v>_amd64.deb
#
# 说明：
# - 容器内先构建前端（pnpm）再构建/打包桌面壳（npm）——保证 renderer/ 有产物。
# - electron 二进制与 electron-builder 资源经宿主缓存卷复用，减少重复下载。
# - 内网受限时可设 ELECTRON_MIRROR / ELECTRON_BUILDER_BINARIES_MIRROR。
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
IMAGE="${ASTRA_LINUX_BUILDER_IMAGE:-electronuserland/builder:20}"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未找到 docker。本脚本须在已安装 Docker 的 Linux 宿主上运行。" >&2
  exit 1
fi

mkdir -p "${HOME}/.cache/electron" "${HOME}/.cache/electron-builder"

echo "[build-linux] 仓库根：${REPO_ROOT}"
echo "[build-linux] 镜像：${IMAGE}"

# 镜像/加速源转发（设计 §11 D-7：内网/受限网络）。仅在设置了对应宿主环境变量时转发：
#   ELECTRON_MIRROR                    —— electron 二进制镜像
#   ELECTRON_BUILDER_BINARIES_MIRROR   —— electron-builder 工具（appimage 等）镜像
#   NPM_CONFIG_REGISTRY                —— npm/pnpm 注册表
# 用法示例：
#   ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/ \
#   ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
#   NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
#   bash apps/desktop/scripts/build-linux-docker.sh
ENV_ARGS=()
for _var in ELECTRON_MIRROR ELECTRON_BUILDER_BINARIES_MIRROR NPM_CONFIG_REGISTRY; do
  if [ -n "${!_var:-}" ]; then
    ENV_ARGS+=(-e "${_var}")
    echo "[build-linux] 转发环境变量：${_var}"
  fi
done

docker run --rm \
  "${ENV_ARGS[@]}" \
  -v "${REPO_ROOT}":/project \
  -w /project \
  -v "${HOME}/.cache/electron":/root/.cache/electron \
  -v "${HOME}/.cache/electron-builder":/root/.cache/electron-builder \
  "${IMAGE}" \
  bash -lc '
    set -euo pipefail
    corepack enable
    # 1) 构建前端产物（apps/web/dist）
    pnpm install --frozen-lockfile --ignore-scripts
    pnpm --filter @astra/web build
    # 2) 独立安装桌面壳依赖并打包 Linux（AppImage + deb）
    cd apps/desktop
    npm install --frozen-lockfile --ignore-scripts
    npm run sync:renderer
    npm run dist:linux
  '

echo "[build-linux] 完成。产物见：${REPO_ROOT}/apps/desktop/release/"
