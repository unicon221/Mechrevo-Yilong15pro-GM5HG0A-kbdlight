#!/usr/bin/env python3
"""Yilong15pro-kbdlight-gui — 机械革命翼龙15Pro 键盘背光图形界面（PySide6 / Qt6）

架构（2026-10-16 改版）：
    ★ 本进程以【普通用户】运行，完全融入桌面会话（KDE/Wayland）。
      所有 EC 读写通过 `sudo Yilong15pro-kbdlight` 子进程转发（/etc/sudoers.d/Yilong15pro-kbdlight
      已配 NOPASSWD 免密）。

    为什么不用 root 跑整个 GUI：
      · root 读不到用户的 ~/.config/kdeglobals → 主题/字体/图标不跟随
      · 输入法、剪贴板、Wayland 缩放等都会出问题
      · 提权还会清掉 WAYLAND_DISPLAY/XDG_RUNTIME_DIR，容易回退到 XWayland

    代价：每次读写多一次进程启动（约 20 ms），对 2 秒轮询完全无感。

    Yilong15pro-kbdlight.py 的纯计算函数（to_level / from_levels / rgb_to_hex /
    PALETTE / 常量）直接 import，不需要 root，零开销。

前提：
    /etc/sudoers.d/Yilong15pro-kbdlight 里给当前用户 NOPASSWD 运行 Yilong15pro-kbdlight
    （否则每一步都会弹密码框）。

用法：
    Yilong15pro-kbdlight-gui                 # 普通用户直接运行
    Yilong15pro-kbdlight-gui --read-only     # 只读（不执行任何 sudo 写操作）
"""

from __future__ import annotations

__version__ = "0.4"

import json
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# 导入主模块
#
# 支持三种安装形式：
#   1) 源码目录        —— 同目录的 Yilong15pro-kbdlight.py
#   2) Arch 包        —— /usr/lib/Yilong15pro-kbdlight/yilong_kbdlight.py
#   3) install.sh     —— /usr/local/bin/Yilong15pro-kbdlight（无 .py 后缀）
# 后两种无 .py 后缀或不在 sys.path，所以用 importlib 按路径加载。
# ---------------------------------------------------------------------------

def _load_kbdlight():
    # 先试常规 import（包已把 yilong_kbdlight.py 放进 site-packages 时用）
    try:
        import yilong_kbdlight          # noqa: F401
        return yilong_kbdlight
    except ImportError:
        pass

    import importlib.machinery
    import importlib.util

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "Yilong15pro-kbdlight.py"),        # 源码目录
        "/usr/lib/Yilong15pro-kbdlight/yilong_kbdlight.py",   # Arch 包
        "/usr/local/bin/Yilong15pro-kbdlight",                # install.sh
        "/usr/bin/Yilong15pro-kbdlight",                      # Arch 包
        os.path.join(here, "Yilong15pro-kbdlight"),
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        loader = importlib.machinery.SourceFileLoader(
            "yilong_kbdlight", path)
        spec = importlib.util.spec_from_file_location(
            "yilong_kbdlight", path, loader=loader)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["yilong_kbdlight"] = mod
        loader.exec_module(mod)
        return mod

    raise ImportError(
        "找不到 yilong_kbdlight 主模块。请先安装：\n"
        "    sudo pacman -S Yilong15pro-kbdlight      # 或 makepkg -si\n"
        "    ./install.sh                              # 或本仓库脚本")


kbdlight = _load_kbdlight()

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QFrame, QGroupBox,
    QColorDialog, QMessageBox, QStatusBar, QToolButton, QSizePolicy,
    QSpacerItem,
)


# --------------------------------------------------------------------------
# EC 访问代理（普通用户 -> sudo Yilong15pro-kbdlight 子进程）
# --------------------------------------------------------------------------

class EcError(kbdlight.KbdLightError):
    """代理层自身的错误（找不到可执行文件、sudo 失败等）。"""


class Ec:
    """通过 `sudo Yilong15pro-kbdlight` 子进程读写 EC。

    Yilong15pro-kbdlight 找不到时回退到 `sudo python3 /path/to/kbdlight.py`，
    这样源码目录直接跑也工作。
    """

    def __init__(self, force_local: bool = False):
        self.force_local = force_local
        self.target = self._find_target()
        self._local = (force_local or self.target is None)
        self.last_error = None

    def _find_target(self):
        """返回 [cmd...] 前缀，或者 None 表示只能本地（需 root）。"""
        exe = shutil.which("Yilong15pro-kbdlight")
        if exe:
            return [exe]
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "Yilong15pro-kbdlight.py")
        if os.path.exists(here):
            return [sys.executable, here]
        return None

    def _run(self, args):
        """跑一次 Yilong15pro-kbdlight，返回 stdout。非零退出码抛 EcError。"""
        if self.force_local:
            raise EcError("只读模式：未执行任何写操作")

        if self._local:
            # 已是 root（或开发模式）：直接调模块，零开销
            if os.geteuid() == 0:
                from io import StringIO
                import contextlib
                buf = StringIO()
                rc = 0
                try:
                    with contextlib.redirect_stdout(buf):
                        rc = kbdlight.main(args)
                except SystemExit as e:
                    rc = e.code or 0
                if rc:
                    raise EcError(f"Yilong15pro-kbdlight 返回 {rc}")
                return buf.getvalue()
            raise EcError(
                "需要 root 权限，且找不到 Yilong15pro-kbdlight 命令。\n"
                "请安装： sudo install -m 755 Yilong15pro-kbdlight.py /usr/bin/Yilong15pro-kbdlight")

        cmd = ["sudo", "-n"] + self.target + ["--no-sudo"] + args
        env = dict(os.environ, KBDLIGHT_NO_SUDO="1")
        try:
            p = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=10, env=env)
        except FileNotFoundError as e:
            raise EcError(f"找不到 sudo: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise EcError("Yilong15pro-kbdlight 超时（EC 无响应？）") from e

        if p.returncode != 0:
            msg = (p.stderr or p.stdout or "").strip()
            if "password" in msg.lower() or "sudo" in msg.lower():
                msg += ("\n\n提示: 请配置免密 sudo：\n"
                        "  unicon ALL=(root) NOPASSWD: /usr/bin/Yilong15pro-kbdlight\n"
                        "   运行: sudo Yilong15pro-kbdlight-setup-sudo")
            raise EcError(msg or f"sudo Yilong15pro-kbdlight 失败 (code {p.returncode})")
        return p.stdout
    # -- 高层接口，与主模块同名 -----------------------------------------

    def read_state(self) -> dict:
        """读完整状态（JSON 模式），返回 dict。"""
        try:
            out = self._run(["state"])   # state = read_state JSON
            return json.loads(out)
        except (json.JSONDecodeError, EcError) as e:
            self.last_error = str(e)
            return {"available": False, "error": str(e), "levels": None,
                    "rgb": None, "hex": None, "lit": None, "percent": None,
                    "support": None, "rgb_supported": None, "trigger": None,
                    "welcome": None, "singlekbl": None, "singlekbl_ok": None,
                    "defaults": None}

    def set_levels(self, r, g, b) -> None:
        """写电平并点亮。用 read → 改 → 写 的原子命令：
        Yilong15pro-kbdlight 没有「直接给电平」的 CLI，但 set_levels 等效于按电平
        对应的 0..255 颜色写入（电平 0 走不到，因为 set_rgb 会夹成 0）。

        更简单可靠：写一个专用的一次性脚本。这里用 `brightness` 不行，
        所以直接调用内部接口 —— Yilong15pro-kbdlight 提供 `levels` 子命令。
        """
        self._run(["levels", str(int(r)), str(int(g)), str(int(b))])

    def set_rgb(self, r, g, b) -> None:
        self._run(["%02X%02X%02X" % (int(r) & 0xFF, int(g) & 0xFF,
                                      int(b) & 0xFF)])

    def off(self) -> None:
        self._run(["off"])

    def on(self) -> None:
        self._run(["on"])

    def is_available(self) -> bool:
        """acpi_call 是否已加载。普通用户直接看文件即可。"""
        return os.path.exists(kbdlight.ACPI_CALL)


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------

def swatch_icon(rgb, size=22) -> QIcon:
    """生成一个圆角色块图标，用于色板按钮。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(*rgb))
    p.setPen(QColor(0, 0, 0, 90))
    p.drawRoundedRect(0.5, 0.5, size - 1, size - 1, 5, 5)
    p.end()
    return QIcon(pm)


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


# --------------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------------

class KbdLightWindow(QMainWindow):
    POLL_MS = 2000          # 状态轮询间隔
    DEFAULT_COLOR = (255, 102, 0)   # 兜底颜色（橙）

    def __init__(self, read_only: bool = False):
        super().__init__()
        self.read_only = read_only

        # ★ EC 访问代理：普通用户进程 -> sudo Yilong15pro-kbdlight 子进程。
        #   read_only 时连读也不走（实际上读也可以，但避免任何 sudo 调用）。
        self.ec = Ec(force_local=read_only)

        # ★ 用户「意图」颜色（0..255）—— 永久保持，**不被轮询覆盖**。
        #   亮度调整只作用于它算出的电平，绝不修改它本身。
        #   这样才能做到：设 #FF6600 → 亮度 50% → 回到 100% → 仍是 #FF6600。
        self._target_rgb = tuple(self.DEFAULT_COLOR)
        # 仅用于绘制预览色块（跟随 _target_rgb）
        self._current = QColor(*self._target_rgb)
        self._updating = False      # 防止回写信号造成递归
        self._last_state = None
        # ★ 关灯前的亮度档（0..50）—— 供「开灯」恢复，避免回弹到最亮
        self._last_level = kbdlight.LEVEL_SCALES

        self.setWindowTitle(f"机械革命翼龙15Pro-键盘背光 ({__version__})")
        self.setMinimumWidth(460)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(14)

        outer.addWidget(self._build_power_group())
        outer.addWidget(self._build_color_group())
        outer.addWidget(self._build_brightness_group())
        outer.addWidget(self._build_palette_group())
        outer.addWidget(self._build_diag_group())
        outer.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum,
                                  QSizePolicy.Expanding))

        self.setStatusBar(QStatusBar())
        self._refresh_status()

        # 定时轮询（只读状态，开销很小）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(self.POLL_MS)

        self._apply_read_only()
        self._poll(initial=True)

    # ------------------------------------------------------------------
    # 界面构建
    # ------------------------------------------------------------------

    def _build_power_group(self) -> QGroupBox:
        g = QGroupBox("开关")
        lay = QHBoxLayout(g)
        lay.setSpacing(10)

        self.btn_on = QPushButton("开灯")
        self.btn_off = QPushButton("关灯")
        self.btn_on.setMinimumHeight(36)
        self.btn_off.setMinimumHeight(36)
        self.btn_on.clicked.connect(self._do_on)
        self.btn_off.clicked.connect(self._do_off)

        lay.addWidget(self.btn_on)
        lay.addWidget(self.btn_off)
        return g

    def _build_color_group(self) -> QGroupBox:
        g = QGroupBox("颜色")
        lay = QVBoxLayout(g)
        lay.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.color_preview = QLabel()
        self.color_preview.setFixedSize(56, 40)
        self.color_preview.setToolTip("当前颜色")

        self.color_text = QLabel("#000000")
        f = self.color_text.font()
        f.setPointSize(f.pointSize() + 3)
        f.setBold(True)
        self.color_text.setFont(f)

        self.btn_pick = QPushButton("选择颜色…")
        self.btn_pick.setMinimumHeight(34)
        self.btn_pick.clicked.connect(self._pick_color)

        row.addWidget(self.color_preview)
        row.addWidget(self.color_text)
        row.addStretch(1)
        row.addWidget(self.btn_pick)
        lay.addLayout(row)
        return g

    def _build_brightness_group(self) -> QGroupBox:
        g = QGroupBox("亮度")
        lay = QVBoxLayout(g)
        lay.setSpacing(6)

        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(kbdlight.LEVEL_SCALES)   # 0..50，0 = 灭灯
        self.slider.setValue(kbdlight.LEVEL_SCALES)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(5)
        self.slider.valueChanged.connect(self._brightness_changed)

        self.lbl_bri = QLabel("50 / 50  (100%)")
        self.lbl_bri.setMinimumWidth(120)
        self.lbl_bri.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row.addWidget(self.slider, 1)
        row.addWidget(self.lbl_bri)
        lay.addLayout(row)

        hint = QLabel("滑条直接对应 EC 电平 1–50；拖到 0 = 关灯")
        hint.setStyleSheet("color: palette(mid); font-size: 11px;")
        lay.addWidget(hint)
        return g

    def _build_palette_group(self) -> QGroupBox:
        g = QGroupBox("预设")
        grid = QGridLayout(g)
        grid.setSpacing(6)

        for i, (name, rgb) in enumerate(kbdlight.PALETTE):
            b = QToolButton()
            b.setIcon(swatch_icon(rgb))
            b.setIconSize(QSize(22, 22))
            b.setToolTip(f"{name}  {kbdlight.rgb_to_hex(rgb)}")
            b.setAutoRaise(True)
            b.setMinimumSize(34, 34)
            b.clicked.connect(lambda _=False, c=rgb: self._apply_rgb(c))
            grid.addWidget(b, i // 8, i % 8)
        return g

    def _build_diag_group(self) -> QGroupBox:
        g = QGroupBox("状态")
        g.setCheckable(True)
        g.setChecked(False)                 # 默认折叠
        lay = QVBoxLayout(g)
        lay.setSpacing(4)

        self.lbl_diag = QLabel("…")
        self.lbl_diag.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_diag.setStyleSheet(
            "font-family: monospace; font-size: 11px;")
        lay.addWidget(self.lbl_diag)

        self.btn_refresh = QPushButton("立即刷新")
        self.btn_refresh.clicked.connect(lambda: self._poll(force=True))
        lay.addWidget(self.btn_refresh)

        g.toggled.connect(lambda on: self.lbl_diag.setVisible(on)
                          or self.btn_refresh.setVisible(on))
        self.lbl_diag.setVisible(False)
        self.btn_refresh.setVisible(False)
        return g

    # ------------------------------------------------------------------
    # 状态刷新
    # ------------------------------------------------------------------

    def _poll(self, initial: bool = False, force: bool = False) -> None:
        st = self.ec.read_state()
        if not force and st == self._last_state and not initial:
            return
        self._last_state = st

        if st["error"]:
            self.statusBar().showMessage(f"⚠ {st['error']}")
            self.lbl_diag.setText(st["error"])
            return

        # 状态栏显示 EC 的真实读数（含量化后的近似值），
        # 而颜色预览/编码显示用户的意图色 —— 两者刻意区分。
        self.statusBar().showMessage(
            f"EC: 电平 {st['levels'][0]}/{st['levels'][1]}/{st['levels'][2]}"
            f"   {st['hex']}   {st['percent']:.0f}%"
            f"   {'点亮' if st['lit'] else '熄灭'}")

        self.lbl_diag.setText(
            f"电平      {st['levels'][0]:2d} {st['levels'][1]:2d} {st['levels'][2]:2d}"
            f"   (0..{kbdlight.LEVEL_MAX}，0=全灭)\n"
            f"RGB       {st['hex']}   {st['percent']:.1f}%\n"
            f"SUPPORT   0x{st['support']:02X}  RGB支持={st['rgb_supported']}\n"
            f"TRIGGER   0x{st['trigger']:02X}  welcome={st['welcome']}\n"
            f"SINGLEKBL 0x{st['singlekbl']:02X}"
            f"  {'OK' if st['singlekbl_ok'] else '⚠ 应为 0x01'}\n"
            f"DEFAULT   {st['defaults'][0]:2d} {st['defaults'][1]:2d} "
            f"{st['defaults'][2]:2d}"
        )

        # 同步界面（避免用户正在拖动时被打断）
        # ★ 注意：只同步滑条位置，**不覆盖 _target_rgb**。
        #   颜色预览永远显示用户意图色，不显示 EC 量化后的近似值。
        if not self._updating:
            self._updating = True
            try:
                top = max(st["levels"])
                self.slider.setValue(0 if not st["lit"] else top)
                self.lbl_bri.setText(
                    f"{top} / {kbdlight.LEVEL_MAX}"
                    f"  ({kbdlight.level_to_percent(top):.0f}%)")
            finally:
                self._updating = False

    def _refresh_status(self) -> None:
        self._paint_preview()

    def _paint_preview(self) -> None:
        """绘制预览色块。显示的是**用户意图色**（_target_rgb），
        而不是 EC 回读的量化值，避免低亮度时颜色编码乱跳。"""
        c = QColor(*self._target_rgb)
        self._current = c
        self.color_preview.setStyleSheet(
            f"background-color: {c.name()};"
            " border: 1px solid palette(mid); border-radius: 6px;")
        self.color_text.setText(c.name().upper())

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------

    def _apply_rgb(self, rgb) -> None:
        """采用一个颜色：记录为意图色，并按当前亮度档写到 EC。"""
        if self.read_only:
            return
        self._target_rgb = tuple(int(x) & 0xFF for x in rgb)
        lvl = self.slider.value() or kbdlight.LEVEL_SCALES
        try:
            self._write_target(lvl)
        except kbdlight.KbdLightError as e:
            self._error(str(e))
            return
        self._paint_preview()
        if self.slider.value() == 0:
            self._updating = True
            self.slider.setValue(kbdlight.LEVEL_SCALES)
            self._updating = False
        QTimer.singleShot(120, lambda: self._poll(force=True))

    def _write_target(self, level: int) -> None:
        """把意图色按指定电平写到 EC。

        ★ 关键：从 _target_rgb（用户意图的 0..255 颜色）换算电平，
          而不是从 EC 回读值算 —— 否则反复拖动滑条会因量化误差累积
          而颜色漂移。

          映射：最亮通道恰好 = level，其余通道按其在 0..255 中的
          相对比例换算到 0..level，再走统一的 to_level() 换算。

          例：#FF6600 (255,102,0) 在 level=50 时 -> (50, 20, 0)
              在 level=25 时 -> (25, 10, 0)
        """
        r, g, b = self._target_rgb
        mx = max(r, g, b)
        if mx == 0:
            self.ec.off()
            return
        # ★ 只要真正写了非 0 亮度，就记住这一档，供「开灯」恢复
        if level > 0:
            self._last_level = level
        # 把每个通道从 0..255 线性映射到 0..level，四舍五入。
        # 最亮通道（mx）必然得到 level，其余按比例。
        # 例：#FF6600 (255,102,0) level=50 -> (50, 20, 0)
        vals = []
        for v in (r, g, b):
            if v == 0:
                vals.append(0)
            else:
                lv = int(round(v / float(mx) * level))
                vals.append(max(kbdlight.LEVEL_MIN, min(level, lv)))
        # 最亮通道精确定位到 level（消除舍入误差）
        for i, v in enumerate((r, g, b)):
            if v == mx:
                vals[i] = level
                break
        nr, ng, nb = vals
        self.ec.set_levels(nr, ng, nb)
        kbdlight.save_state(kbdlight.from_levels((nr, ng, nb)))

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(
            QColor(*self._target_rgb), self, "选择键盘颜色",
            QColorDialog.DontUseNativeDialog)
        if c.isValid():
            self._apply_rgb((c.red(), c.green(), c.blue()))

    def _brightness_changed(self, value: int) -> None:
        self.lbl_bri.setText(
            f"{value} / {kbdlight.LEVEL_SCALES}"
            f"  ({kbdlight.level_to_percent(value):.0f}%)")
        if self._updating or self.read_only:
            return
        try:
            if value == 0:
                self.ec.off()
            else:
                self._write_target(value)
        except kbdlight.KbdLightError as e:
            self._error(str(e))

    def _do_on(self) -> None:
        """点亮：恢复关灯前的颜色与亮度档。

        ★ 不再写死最高亮度 —— 用 _last_level 记住关灯前的滑条档位。
        ★ 不用 kbdlight.load_state()：那个文件（/var/lib/Yilong15pro-kbdlight/state）
          由 root 写，普通用户读不到。颜色改从 EC 回读（或者用意图色）。
        """
        if self.read_only:
            return
        st = self.ec.read_state()
        if st.get("levels") and max(st["levels"]) > 0:
            # EC 里还有颜色（比如被别的程序点亮了）—— 采纳它
            self._target_rgb = tuple(st["rgb"])
        # 恢复到关灯前那一档；若从未关过灯则用最高档
        level = self._last_level or kbdlight.LEVEL_SCALES
        try:
            self._write_target(level)
        except kbdlight.KbdLightError as e:
            self._error(str(e))
            return
        self._paint_preview()
        self._updating = True
        self.slider.setValue(level)
        self._updating = False
        QTimer.singleShot(120, lambda: self._poll(force=True))

    def _do_off(self) -> None:
        if self.read_only:
            return
        try:
            self.ec.off()
        except kbdlight.KbdLightError as e:
            self._error(str(e))
            return
        self._updating = True
        self.slider.setValue(0)
        self._updating = False
        QTimer.singleShot(120, lambda: self._poll(force=True))

    def _error(self, msg: str) -> None:
        QMessageBox.warning(self, "操作失败", msg)
        self.statusBar().showMessage(f"⚠ {msg}")

    # ------------------------------------------------------------------

    def _apply_read_only(self) -> None:
        if not self.read_only:
            return
        for w in (self.btn_on, self.btn_off, self.btn_pick, self.slider):
            w.setEnabled(False)
        self.setWindowTitle(self.windowTitle() + "  [只读]")


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def _app_icon() -> QIcon:
    """取应用图标。

    优先级：
      1) 主题图标（Yilong15pro-kbdlight）—— 安装后会命中 /usr/share/icons/hicolor/...
      2) 脚本同目录的 kbdlight.svg
      3) 现场用 QPainter 画一个（保底）
    """
    ic = QIcon.fromTheme("Yilong15pro-kbdlight")
    if not ic.isNull() and ic.availableSizes():
        return ic

    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "Yilong15pro-kbdlight.svg"),
                 "/usr/share/icons/hicolor/scalable/apps/Yilong15pro-kbdlight.svg"):
        if os.path.isfile(cand):
            ic = QIcon(cand)
            if not ic.isNull():
                return ic

    # 保底：画一枚小键盘
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(43, 43, 49))
    p.setPen(QColor(74, 74, 82))
    p.drawRoundedRect(3, 12, 58, 40, 7, 7)
    for i, c in enumerate((QColor(255, 59, 48), QColor(52, 199, 89),
                           QColor(10, 132, 255))):
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(10 + i * 16, 20, 12, 10, 2, 2)
    p.end()
    return QIcon(pm)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if any(a in ("-V", "--version") for a in argv):
        print(f"Yilong15pro-kbdlight-gui {__version__}"
              f"  (Yilong15pro-kbdlight {kbdlight.__version__})")
        return 0

    read_only_flag = ("--read-only" in argv) or ("--no-elevate" in argv)

    app = QApplication(sys.argv)
    app.setApplicationName("Yilong15pro-kbdlight-gui")
    app.setApplicationDisplayName("键盘背光")
    # ★ 让 Wayland/KDE 能把窗口关联到 kbdlight.desktop，从而显示正确图标
    app.setDesktopFileName("Yilong15pro-kbdlight")
    app.setWindowIcon(_app_icon())

    # 报告实际使用的 Qt 平台后端（便于排查 Wayland/xcb 问题）
    print(f"Qt platform: {app.platformName()}   "
          f"(session={os.environ.get('XDG_SESSION_TYPE', '?')})",
          file=sys.stderr)

    # acpi_call 检查（只看文件，不需要 root）
    if not os.path.exists(kbdlight.ACPI_CALL):
        QMessageBox.critical(
            None, "缺少 acpi_call",
            f"{kbdlight.ACPI_CALL} 不存在。\n\n请先运行：\n"
            "    sudo modprobe acpi_call\n\n"
            "或永久启用：\n"
            "    echo acpi_call | sudo tee /etc/modules-load.d/acpi_call.conf")
        return 1

    # 探测 sudo 免密是否就绪；不可写时自动降级为只读并告知原因
    read_only = read_only_flag
    if not read_only and os.geteuid() != 0:
        try:
            Ec()._run(["state"])
        except kbdlight.KbdLightError as e:
            read_only = True
            QMessageBox.warning(
                None, "无写权限，已进入只读模式",
                f"无法通过 sudo 调用 Yilong15pro-kbdlight：\n\n{e}\n\n"
                "界面仍可查看状态，但不能修改。")

    win = KbdLightWindow(read_only=read_only)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
