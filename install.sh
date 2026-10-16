#!/usr/bin/env bash
# Yilong15pro-kbdlight 安装脚本 — 机械革命翼龙15Pro 键盘背光
#
# 用法：
#   ./install.sh              # 安装 CLI + GUI + 免密 sudo 规则
#   ./install.sh --cli-only   # 只装 CLI
#   ./install.sh --uninstall  # 卸载
#
# 需要 root（脚本内部调用 sudo）。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="/usr/local/bin"
SUDOERS="/etc/sudoers.d/Yilong15pro-kbdlight"
TARGET_USER="${SUDO_USER:-${USER:-$(id -un)}}"

# 若已用 pacman 安装（/usr/bin/Yilong15pro-kbdlight），则不重复装到 /usr/local/bin ——
# 这会遮蔽包版本，导致升级时行为不一致。
PKG_INSTALLED=0
if pacman -Q Yilong15pro-kbdlight >/dev/null 2>&1; then
  PKG_INSTALLED=1
fi

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

CLI_ONLY=0
UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --cli-only)  CLI_ONLY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)
      sed -n '3,9p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) die "未知参数: $a" ;;
  esac
done

# ---------------------------------------------------------------------------
# 卸载
# ---------------------------------------------------------------------------
if (( UNINSTALL )); then
  say "卸载 Yilong15pro-kbdlight"
  sudo rm -f "$BIN_DIR/Yilong15pro-kbdlight" "$BIN_DIR/Yilong15pro-kbdlight-gui"
  sudo rm -f "$SUDOERS"
  sudo rm -f /usr/share/applications/Yilong15pro-kbdlight.desktop
  sudo rm -f /usr/share/icons/hicolor/scalable/apps/Yilong15pro-kbdlight.svg
  for s in 16 24 32 48 64 128 256 512; do
    sudo rm -f "/usr/share/icons/hicolor/${s}x${s}/apps/Yilong15pro-kbdlight.png"
  done
  command -v update-desktop-database >/dev/null && \
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
  command -v gtk-update-icon-cache >/dev/null && \
    sudo gtk-update-icon-cache -qtf /usr/share/icons/hicolor >/dev/null 2>&1 || true
  say "完成。（未改动 /etc/modules-load.d/acpi_call.conf，如需移除请手动处理）"
  exit 0
fi

# ---------------------------------------------------------------------------
# 如果已用 pacman 装过，直接退出并提示
# ---------------------------------------------------------------------------
if (( PKG_INSTALLED )); then
  warn "已检测到 pacman 包 kbdlight（/usr/bin/Yilong15pro-kbdlight）"
  warn "无需再跑 install.sh。如需配置免密 sudo："
  warn "    sudo Yilong15pro-kbdlight-setup-sudo"
  warn "卸载： sudo pacman -R Yilong15pro-kbdlight"
  exit 0
fi

# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------
say "检查前置条件"

[ -f "$HERE/Yilong15pro-kbdlight.py" ] || die "找不到 $HERE/Yilong15pro-kbdlight.py（请在项目目录中运行）"

if ! command -v python3 >/dev/null; then
  die "缺少 python3"
fi

if [ -e /sys/module/acpi_call ]; then
  say "acpi_call 模块已加载"
else
  warn "acpi_call 模块未加载"
  if command -v modprobe >/dev/null; then
    if sudo modprobe acpi_call 2>/dev/null; then
      say "已加载 acpi_call"
    else
      warn "modprobe acpi_call 失败 —— 可能未安装 acpi_call 内核模块"
      warn "  Arch:  sudo pacman -S acpi_call"
      warn "  Debian/Ubuntu: sudo apt install acpi-call-dkms"
    fi
  fi
fi

if [ ! -e /proc/acpi/call ]; then
  warn "/proc/acpi/call 不存在 —— 装好 acpi_call 后再运行本脚本"
fi

# ---------------------------------------------------------------------------
# 安装 CLI
# ---------------------------------------------------------------------------
say "安装 CLI  ->  $BIN_DIR/Yilong15pro-kbdlight"
sudo install -m 755 "$HERE/Yilong15pro-kbdlight.py" "$BIN_DIR/Yilong15pro-kbdlight"

# ---------------------------------------------------------------------------
# 安装 GUI（可选）
# ---------------------------------------------------------------------------
if (( ! CLI_ONLY )); then
  if [ -f "$HERE/Yilong15pro-kbdlight-gui.py" ]; then
    if python3 -c 'import PySide6' 2>/dev/null; then
      say "安装 GUI  ->  $BIN_DIR/Yilong15pro-kbdlight-gui"
      sudo install -m 755 "$HERE/Yilong15pro-kbdlight-gui.py" "$BIN_DIR/Yilong15pro-kbdlight-gui"

      # 桌面入口 + 图标（让 GUI 出现在应用菜单里）
      if [ -f "$HERE/Yilong15pro-kbdlight.desktop" ]; then
        say "安装桌面入口  ->  /usr/share/applications/Yilong15pro-kbdlight.desktop"
        sudo install -Dm644 "$HERE/Yilong15pro-kbdlight.desktop" \
             /usr/share/applications/Yilong15pro-kbdlight.desktop
      fi

      if [ -f "$HERE/Yilong15pro-kbdlight.svg" ]; then
        say "安装图标（hicolor 主题）"
        sudo install -Dm644 "$HERE/Yilong15pro-kbdlight.svg" \
             /usr/share/icons/hicolor/scalable/apps/Yilong15pro-kbdlight.svg
        if [ -d "$HERE/icons/hicolor" ]; then
          for s in 16 24 32 48 64 128 256 512; do
            src_png="$HERE/icons/hicolor/${s}x${s}/apps/Yilong15pro-kbdlight.png"
            [ -f "$src_png" ] || continue
            sudo install -Dm644 "$src_png" \
                 "/usr/share/icons/hicolor/${s}x${s}/apps/Yilong15pro-kbdlight.png"
          done
        fi
      fi

      # 刷新桌面/图标缓存
      if command -v update-desktop-database >/dev/null; then
        sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
      fi
      if command -v gtk-update-icon-cache >/dev/null; then
        sudo gtk-update-icon-cache -qtf /usr/share/icons/hicolor >/dev/null 2>&1 || true
      fi
    else
      warn "未检测到 PySide6，跳过 GUI。安装后可重跑本脚本："
      warn "  Arch:  sudo pacman -S pyside6"
      warn "  Debian/Ubuntu: sudo apt install python3-pyside6.qtwidgets"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 免密 sudo 规则
# ---------------------------------------------------------------------------
say "写入免密规则  ->  $SUDOERS  (用户: $TARGET_USER)"

# 只允许运行这两个绝对路径，且不跟随其他参数 —— 仍是精确白名单。
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
{
  echo "# Yilong15pro-kbdlight — 键盘背光免密规则（由 install.sh 生成）"
  echo "$TARGET_USER ALL=(root) NOPASSWD: $BIN_DIR/Yilong15pro-kbdlight"
  if [ -x "$BIN_DIR/Yilong15pro-kbdlight-gui" ] || (( ! CLI_ONLY )); then
    echo "$TARGET_USER ALL=(root) NOPASSWD: $BIN_DIR/Yilong15pro-kbdlight-gui"
  fi
} > "$tmp"

# visudo -c 校验，语法错会导致 sudo 全盘失效，务必先验
if sudo visudo -cf "$tmp" >/dev/null; then
  sudo install -m 440 -o root -g root "$tmp" "$SUDOERS"
  say "免密规则已生效（无需重新登录）"
else
  die "sudoers 语法校验失败，已放弃写入"
fi

# 开机自动加载 acpi_call
if [ -d /etc/modules-load.d ] && [ ! -e /etc/modules-load.d/acpi_call.conf ]; then
  say "配置开机自动加载 acpi_call"
  echo acpi_call | sudo tee /etc/modules-load.d/acpi_call.conf >/dev/null
fi

# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
say "自检"
if [ -e /proc/acpi/call ]; then
  if sudo -n "$BIN_DIR/Yilong15pro-kbdlight" read >/dev/null 2>&1; then
    say "读写测试通过 —— 试试: Yilong15pro-kbdlight ff0000"
  else
    warn "读写测试失败。请确认 acpi_call 已加载：sudo modprobe acpi_call"
  fi
else
  warn "跳过（/proc/acpi/call 不存在）"
fi

cat <<EOF

安装完成。快速上手：

    Yilong15pro-kbdlight ff0000            # 红色
    Yilong15pro-kbdlight off               # 关灯（真全灭）
    sudo Yilong15pro-kbdlight read         # 查看 EC 状态
    Yilong15pro-kbdlight-gui               # 图形界面（普通用户运行，不要 sudo）

EOF
