#!/usr/bin/env python3
"""kbdlight-gui — 机械革命翼龙15Pro 键盘背光图形界面（PySide6 / Qt6）

架构：
    本进程以 root 运行（通过 pkexec/sudo 启动），直接 import kbdlight 模块
    读写 EC —— 没有 subprocess、没有 socket、没有轮询开销。

    /proc/acpi/call 是 root 私有（rw-rw---- root），所以读写都需要 root。
    因此 GUI 整体以 root 启动，而不是「读免 sudo，写走 subprocess」。

用法：
    kbdlight-gui                    # 若已配置 pkexec/sudo 则自动提权
    sudo kbdlight-gui               # 直接以 root 运行
    kbdlight-gui --no-elevate       # 不自动提权（调试用，只能看不能改）
"""

from __future__ import annotations

import os
import sys

# 让 GUI 能在源码目录直接运行
try:
    import kbdlight
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kbdlight

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QSlider, QFrame, QGroupBox,
    QColorDialog, QMessageBox, QStatusBar, QToolButton, QSizePolicy,
    QScrollArea, QSpacerItem,
)


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

        # ★ 用户「意图」颜色（0..255）—— 永久保持，**不被轮询覆盖**。
        #   亮度调整只作用于它算出的电平，绝不修改它本身。
        #   这样才能做到：设 #FF6600 → 亮度 50% → 回到 100% → 仍是 #FF6600。
        self._target_rgb = tuple(self.DEFAULT_COLOR)
        # 仅用于绘制预览色块（跟随 _target_rgb）
        self._current = QColor(*self._target_rgb)
        self._updating = False      # 防止回写信号造成递归
        self._last_state = None

        self.setWindowTitle("键盘背光 — 机械革命翼龙15Pro")
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
        st = kbdlight.read_state()
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
            f"   (1..{kbdlight.LEVEL_MAX})\n"
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
            kbdlight.off()
            return
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
        kbdlight.set_levels(nr, ng, nb)
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
                kbdlight.off()
            else:
                self._write_target(value)
        except kbdlight.KbdLightError as e:
            self._error(str(e))

    def _do_on(self) -> None:
        if self.read_only:
            return
        rgb = kbdlight.load_state() or self._target_rgb
        self._target_rgb = tuple(rgb)
        try:
            self._write_target(kbdlight.LEVEL_SCALES)
        except kbdlight.KbdLightError as e:
            self._error(str(e))
            return
        self._paint_preview()
        self._updating = True
        self.slider.setValue(kbdlight.LEVEL_SCALES)
        self._updating = False
        QTimer.singleShot(120, lambda: self._poll(force=True))

    def _do_off(self) -> None:
        if self.read_only:
            return
        try:
            kbdlight.off()
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

def _elevate_and_rerun() -> None:
    """非 root 时用 pkexec/sudo 重新启动自己。"""
    exe = os.path.abspath(sys.argv[0])
    args = [a for a in sys.argv[1:] if a != "--no-elevate"]
    if shutil_which := __import__("shutil").which("pkexec"):
        os.execvp(walk := shutil_which, [walk, sys.executable, exe] + args)
    os.execvp("sudo", ["sudo", sys.executable, exe] + args)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    no_elevate = "--no-elevate" in argv
    if no_elevate:
        argv.remove("--no-elevate")

    is_root = (os.geteuid() == 0)

    if not is_root and not no_elevate:
        _elevate_and_rerun()      # 不返回
        return 1

    read_only = not is_root
    if read_only:
        print("提示: 未以 root 运行，界面为只读模式（--no-elevate）",
              file=sys.stderr)

    app = QApplication(sys.argv)
    app.setApplicationName("kbdlight-gui")
    app.setApplicationDisplayName("键盘背光")

    if not kbdlight.is_available():
        QMessageBox.critical(
            None, "缺少 acpi_call",
            f"{kbdlight.ACPI_CALL} 不存在。\n\n请先运行：\n"
            "    sudo modprobe acpi_call\n\n"
            "或永久启用：\n"
            "    echo acpi_call | sudo tee /etc/modules-load.d/acpi_call.conf")
        return 1

    win = KbdLightWindow(read_only=read_only)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
