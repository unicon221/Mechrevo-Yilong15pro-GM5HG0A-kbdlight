# Maintainer: unicon221 <unicon221@users.noreply.github.com>
#
# Arch Linux PKGBUILD — kbdlight
# 机械革命翼龙15Pro (GM5HG0A) 键盘 RGB 背光控制
#
# 构建安装：
#     makepkg -si
#     sudo kbdlight-setup-sudo      # 之后写入免密规则
#
# 说明：
#   · 同时提供 CLI（/usr/bin/kbdlight）与 GUI（/usr/bin/kbdlight-gui）
#   · GUI 依赖 pyside6 —— 放在 optdepends，不用 GUI 的可以只装 CLI
#   · 免密 sudo 规则不在此包内安装。需要时手动运行 kbdlight-setup-sudo，
#     或自己往 /etc/sudoers.d/ 加一行。
#     这样避免包管理器写用户相关的 /etc/sudoers.d 规则。

pkgname=kbdlight
pkgver=0.2
pkgrel=1
pkgdesc="Keyboard RGB backlight control for Mechrevo Yilong 15 Pro (GM5HG0A / Uniwill EC) on Linux"
arch=('any')
url="https://github.com/unicon221/Mechrevo-Yilong15pro-GM5HG0A-kbdlight"
license=('MIT')
depends=('python' 'acpi_call')
optdepends=('pyside6: 图形界面 kbdlight-gui')
provides=('kbdlight')
conflicts=('kbdlight-git')
backup=()
options=('!strip')

# 仓库名（GitHub tarball 的顶层目录是 <repo>-<tag>）
_repo=Mechrevo-Yilong15pro-GM5HG0A-kbdlight

# 从 GitHub 的 v$pkgver 标签取源码
source=("$_repo-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    # GitHub 的 tarball 顶层目录名是 <repo>-<tag>，
    # 即 Mechrevo-Yilong15pro-GM5HG0A-kbdlight-0.2
    # （源代码已在前面声明为 _repo）
    cd "$srcdir/$_repo-$pkgver"

    install -Dm755 kbdlight.py     "$pkgdir/usr/bin/kbdlight"
    install -Dm755 kbdlight-gui.py "$pkgdir/usr/bin/kbdlight-gui"

    # 桌面入口 + 图标
    install -Dm644 kbdlight.desktop \
        "$pkgdir/usr/share/applications/kbdlight.desktop"

    install -Dm644 kbdlight.svg \
        "$pkgdir/usr/share/icons/hicolor/scalable/apps/kbdlight.svg"
    for s in 16 24 32 48 64 128 256 512; do
        install -Dm644 "icons/hicolor/${s}x${s}/apps/kbdlight.png" \
            "$pkgdir/usr/share/icons/hicolor/${s}x${s}/apps/kbdlight.png"
    done

    install -Dm644 README.md   "$pkgdir/usr/share/doc/$pkgname/README.md"
    install -Dm644 PROTOCOL.md "$pkgdir/usr/share/doc/$pkgname/PROTOCOL.md"

    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"

    # 免密 sudo 辅助脚本（可选，用户主动运行才生效）
    install -Dm755 /dev/stdin "$pkgdir/usr/bin/kbdlight-setup-sudo" <<'EOS'
#!/usr/bin/env bash
# kbdlight-setup-sudo —— 为当前用户写入免密 sudo 规则
#
# 由用户手动运行（不在安装时自动执行，避免包管理器改 /etc/sudoers.d）。
#     kbdlight-setup-sudo            # 使用当前用户
#     kbdlight-setup-sudo <username> # 指定用户
set -euo pipefail

USERNAME="${1:-${SUDO_USER:-$(id -un)}}"
RULE_FILE="/etc/sudoers.d/kbdlight"

[ "$(id -u)" -eq 0 ] || { echo "请用 sudo 运行：sudo kbdlight-setup-sudo" >&2; exit 1; }

[ -f /etc/passwd ] && grep -q "^${USERNAME}:" /etc/passwd \
    || { echo "用户不存在: $USERNAME" >&2; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
{
    echo "# kbdlight — 键盘背光免密规则（由 kbdlight-setup-sudo 生成）"
    echo "${USERNAME} ALL=(root) NOPASSWD: /usr/bin/kbdlight"
} > "$TMP"

if visudo -cf "$TMP" >/dev/null; then
    install -m 440 -o root -g root "$TMP" "$RULE_FILE"
    echo "已写入 $RULE_FILE （用户: $USERNAME）"
    echo "现在可以直接运行： kbdlight ff0000"
else
    echo "sudoers 语法校验失败，未写入" >&2
    exit 1
fi
EOS
}
