#!/usr/bin/env python3
"""
kbdlight — 机械革命翼龙15Pro (Uniwill GM5HG0A) 键盘 RGB 背光控制

既可作命令行工具，也可作 Python 模块导入：

    # CLI
    sudo kbdlight ff0000
    sudo kbdlight off
    sudo kbdlight read

    # 模块（写操作需要 root，读操作也需要 —— /proc/acpi/call 是 root 私有）
    import kbdlight
    kbdlight.set_rgb(0xFF, 0x00, 0x00)     # 设红
    r, g, b = kbdlight.get_rgb()           # 0..255 换算值
    levels  = kbdlight.get_levels()        # 1..50 原始电平
    state   = kbdlight.read_state()        # 完整状态字典

协议（逆向自厂商 ControlCenter 的 LightingModel.EC_SPEC）
------------------------------------------------------------------------
键盘背光由 EC 寄存器控制。**关键：改完颜色后必须写触发字节点亮**，
否则寄存器值虽对，灯不亮。

    0x0766  SUPPORT_BYTE2   bit2(0x04) = 支持 RGB 键盘（只读位）
    0x0767  TRIGGER_BYTE    写 0x20 (bit5) = 触发/点亮键盘灯（自清位）
                            0x80 (bit7)      = welcome 模式位（常驻，会导致旋转动画）
    0x0769  R   level (0-50)   ←★★ 不是 0-255！0=全灭
    0x076A  G   level (0-50)
    0x076B  B   level (0-50)
    0x076C/6D/6E  DEFAULT R/G/B level (0-50)
    0x076F  MUSIC_NO
    0x078C  SINGLEKBL_ENABLE / AP_EC_LOGO_CONFIRM   ← 必须 = 1
    0x078E  SINGLEKBL_SUPPORTPOWER / SUPPORT_BYTE6

★★ 三个必须知道的坑
   1) RGBKB_LEVEL_R/G/B 是 0..50 的「电平」，不是 0..255 的颜色值。
      写入 >50 会被 EC 静默丢弃（寄存器回读不变、灯不动）。
   2) 0x078C 必须 = 0x01，否则静态色写入被完全忽略。
   3) ★★ 「当前电平」(0x0769-6B) 会被 EC 的周期任务同步为
      「默认电平」(0x076C-6E)。所以：
        · 关灯必须【同时】把两组都写 0（只写当前电平会 1 秒后被恢复）
        · 改颜色时两组一起写，才不会“抽帧”或回跳
        · 默认电平残留非法值（如 0xFF）会让 EC 灯光任务异常
      off() 已按此实现，实测可稳定全灭 >30 秒。

读写通道：ACPI 方法 \\_SB_.INOU.ECRR / ECRW（与内核 uniwill_laptop
驱动同一条通路），经 acpi_call 收发。地址是 16 位。

依赖
----
    sudo modprobe acpi_call

用法
----
    sudo kbdlight RRGGBB            # 设置颜色并点亮
    sudo kbdlight on                # 点亮（恢复上次颜色或默认色）
    sudo kbdlight off               # 关闭
    sudo kbdlight brightness 0-255  # 亮度（按比例缩放，保持色相）
    sudo kbdlight read              # 读当前状态（支持 --json）
    sudo kbdlight demo              # 循环演示颜色
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

__all__ = [
    # 常量
    "ACPI_CALL", "EC_SCOPE",
    "ADDR_SUPPORT", "ADDR_TRIGGER", "ADDR_R", "ADDR_G", "ADDR_B",
    "ADDR_DEF_R", "ADDR_DEF_G", "ADDR_DEF_B", "ADDR_SINGLEKBL",
    "SINGLEKBL_ENABLE", "TRIGGER_BIT", "WELCOME_BIT", "SUPPORT_BIT",
    "LEVEL_OFF", "LEVEL_MIN", "LEVEL_MAX", "LEVEL_SCALES", "STATE_FILE",
    "is_lit",
    # 异常
    "KbdLightError", "NotRootError", "AcpiCallMissingError",
    # 换算
    "to_level", "from_level", "to_levels", "from_levels",
    "percent_to_level", "level_to_percent",
    # 底层
    "ec_read", "ec_write", "is_available", "check_available",
    # 高层
    "set_levels", "set_rgb", "get_levels", "get_rgb",
    "off", "on", "set_brightness", "set_percent", "read_state",
    "save_state", "load_state", "parse_hex_color", "rgb_to_hex",
    "PALETTE",
    # CLI
    "main",
]

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

ACPI_CALL = "/proc/acpi/call"
EC_SCOPE = "\\_SB_.INOU"

ADDR_SUPPORT = 0x0766
ADDR_TRIGGER = 0x0767
ADDR_R = 0x0769
ADDR_G = 0x076A
ADDR_B = 0x076B
ADDR_DEF_R = 0x076C
ADDR_DEF_G = 0x076D
ADDR_DEF_B = 0x076E
ADDR_SINGLEKBL = 0x078C   # SINGLEKBL_ENABLE / AP_EC_LOGO_CONFIRM

SINGLEKBL_ENABLE = 0x01   # ★ 必须是 1，否则静态色不被接受（实测）

# ★★ 关灯电平。EC 电平合法范围是 0..50，其中：
#     0  = 完全熄灭（无微光）
#     1  = 最暗的「微光」（肉眼在暗环境仍可见）
#    50  = 最亮
#
# ★ 核心机制（2026-10-16 实测）：
#   EC 有周期任务会把「当前电平」0x0769-6B 同步为「默认电平」0x076C-6E。
#   因此要真正全灭，必须【同时】把两组都写 0；只写当前电平会在约 1 秒后
#   被默认电平覆盖回去（表现为灭一下又亮）。
LEVEL_OFF = 0

TRIGGER_BIT = 0x20     # bit5 = EC_RGBKEYBOARD_TRIGGER_BIT（自清）
WELCOME_BIT = 0x80     # bit7 = EC_RGBKEYBOARD_WELCOME_ON_BIT（常驻，会跑旋转动画）
SUPPORT_BIT = 0x04     # bit2

# ★★ RGB 电平范围（GCUService LightingModel.SingleZone 常量）
LEVEL_MIN = 1
LEVEL_MAX = 50         # RGB_LEVEL_MAX = 0x32
LEVEL_SCALES = 50      # RGB_LEVEL_SCALES = 0x32
VALUE_TO_LEVEL_RATIO = 5   # RGB_VALUE_TO_LEVEL_RATIO

STATE_FILE = "/run/kbdlight.last"   # 记录上次颜色，供 on 恢复

# GUI 预设色板（0..255 尺度）
PALETTE = [
    ("红",     (0xFF, 0x00, 0x00)),
    ("橙",     (0xFF, 0x7F, 0x00)),
    ("琥珀",   (0xFF, 0xA5, 0x00)),
    ("黄",     (0xFF, 0xFF, 0x00)),
    ("黄绿",   (0xAD, 0xFF, 0x2F)),
    ("绿",     (0x00, 0xFF, 0x00)),
    ("春绿",   (0x00, 0xFF, 0x7F)),
    ("青",     (0x00, 0xFF, 0xFF)),
    ("天蓝",   (0x00, 0xBF, 0xFF)),
    ("道奇蓝", (0x1E, 0x90, 0xFF)),
    ("蓝",     (0x00, 0x00, 0xFF)),
    ("紫",     (0x8B, 0x00, 0xFF)),
    ("品红",   (0xFF, 0x00, 0xFF)),
    ("粉红",   (0xFF, 0x69, 0xB4)),
    ("白",     (0xFF, 0xFF, 0xFF)),
    ("暖白",   (0xFF, 0xD8, 0xA8)),
]


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------

class KbdLightError(Exception):
    """所有 kbdlight 错误的基类。"""


class NotRootError(KbdLightError):
    """需要 root 权限。"""


class AcpiCallMissingError(KbdLightError):
    """acpi_call 模块未加载。"""


# --------------------------------------------------------------------------
# 换算
# --------------------------------------------------------------------------

def to_level(v) -> int:
    """0..255 通道值 -> EC 的 0..50 电平。

    0 保持 0（该通道熄灭）。非 0 的值会被夹到 1..50；
    超出范围的值 EC 会丢弃，所以这里必须先夹好。
    """
    v = max(0, min(255, int(v)))
    if v == 0:
        return 0
    lvl = int(round(v / 255.0 * LEVEL_SCALES))
    return max(LEVEL_MIN, min(LEVEL_MAX, lvl))


def from_level(lvl) -> int:
    """1..50 电平 -> 0..255 通道值（用于显示/回读）。"""
    lvl = max(0, min(LEVEL_MAX, int(lvl)))
    return int(round(lvl / float(LEVEL_SCALES) * 255))


def to_levels(rgb) -> tuple:
    """(r,g,b) 0..255 -> (lr,lg,lb) 1..50。"""
    return tuple(to_level(x) for x in rgb)


def from_levels(levels) -> tuple:
    """(lr,lg,lb) 1..50 -> (r,g,b) 0..255。"""
    return tuple(from_level(x) for x in levels)


def percent_to_level(pct: float) -> int:
    """0..100 百分比 -> 1..50 电平（保留色相时用不到，仅供直接设定）。"""
    pct = max(0.0, min(100.0, float(pct)))
    if pct <= 0:
        return LEVEL_OFF
    return max(LEVEL_MIN, min(LEVEL_MAX, int(round(pct / 100.0 * LEVEL_SCALES))))


def level_to_percent(lvl: int) -> float:
    """1..50 电平 -> 0..100 百分比。"""
    lvl = max(0, min(LEVEL_MAX, int(lvl)))
    if lvl <= LEVEL_MIN:
        return 0.0
    return round(lvl / float(LEVEL_SCALES) * 100.0, 1)


def is_lit(levels) -> bool:
    """电平是否至少有一个通道 > 0（即有光输出）。"""
    return max(levels) > LEVEL_OFF


# --------------------------------------------------------------------------
# 底层 EC 访问
# --------------------------------------------------------------------------

def _call(invocation: str) -> str:
    """写入一个 ACPI 调用并读回结果。

    /proc/acpi/call 的语义是「写入即调用」，读它得到该次调用的返回值。
    整个文件是 root 私有（rw-rw---- root），所以读和写都需要 root。
    """
    if not os.path.exists(ACPI_CALL):
        raise AcpiCallMissingError(
            f"{ACPI_CALL} 不存在，请先： sudo modprobe acpi_call")
    try:
        with open(ACPI_CALL, "w") as f:
            f.write(invocation)
    except PermissionError as e:
        raise NotRootError(
            f"无法写入 {ACPI_CALL}（需要 root，且 acpi_call 已加载）: {e}") from e
    except OSError as e:
        raise KbdLightError(f"ACPI 调用失败: {e}") from e

    try:
        with open(ACPI_CALL, "rb") as f:
            raw = f.read()
    except PermissionError as e:
        raise NotRootError(f"无法读取 {ACPI_CALL}: {e}") from e
    except OSError:
        return ""
    return raw.replace(b"\0", b"").decode("ascii", "replace").strip()


def ec_read(addr: int) -> int:
    """读一个 EC 寄存器，返回 0..255。"""
    out = _call(f"{EC_SCOPE}.ECRR 0x{addr:04X}")
    m = re.search(r"0x([0-9a-fA-F]+)", out or "")
    if not m:
        raise KbdLightError(f"读 EC 0x{addr:04X} 失败: {out!r}")
    return int(m.group(1), 16) & 0xFF


def ec_write(addr: int, value: int) -> None:
    """写一个 EC 寄存器。"""
    out = _call(f"{EC_SCOPE}.ECRW 0x{addr:04X} 0x{value & 0xFF:02X}")
    if out.lower().startswith("error"):
        raise KbdLightError(f"写 EC 0x{addr:04X} 失败: {out!r}")


def is_available() -> bool:
    """acpi_call 是否已加载（不代表有权限）。"""
    return os.path.exists(ACPI_CALL)


def check_available() -> None:
    """检查环境，不可用时抛异常。"""
    if not is_available():
        raise AcpiCallMissingError(
            f"{ACPI_CALL} 不存在，请先： sudo modprobe acpi_call")
    if os.geteuid() != 0:
        raise NotRootError("需要 root 权限： sudo kbdlight ...")


# --------------------------------------------------------------------------
# 高层 API
# --------------------------------------------------------------------------

def set_levels(lr: int, lg: int, lb: int, trigger: bool = True,
               enable: bool = True, defaults: bool = True) -> None:
    """直接写 0..50 电平并点亮。越界值会被夹取。

    lr/lg/lb 为 0 时对应通道完全熄灭（全 0 即整键盘全灭）。

    defaults 控制是否同步写「默认电平」0x076C/6D/6E。
    ★ 强烈建议保持 True：EC 会周期性地把当前电平同步回默认电平，
      不同步就会在一秒后被恢复（或颜色在两种值之间抖动）。
      只有在你明确想保留开机色时才传 defaults=False。

    enable=False 时不去动 0x078C。
    """
    lr = max(LEVEL_OFF, min(LEVEL_MAX, int(lr)))
    lg = max(LEVEL_OFF, min(LEVEL_MAX, int(lg)))
    lb = max(LEVEL_OFF, min(LEVEL_MAX, int(lb)))
    ec_write(ADDR_R, lr)
    ec_write(ADDR_G, lg)
    ec_write(ADDR_B, lb)
    if defaults:
        # ★★ 必须同步默认电平，否则会被 EC 的周期任务覆盖回去。
        # 同时也避免残留非法值（如 0xFF）让 EC 灯光任务进异常分支。
        ec_write(ADDR_DEF_R, lr)
        ec_write(ADDR_DEF_G, lg)
        ec_write(ADDR_DEF_B, lb)
    if enable:
        # ★ 0x078C 必须为 1，否则静态色不被 EC 接受（实测）。
        ec_write(ADDR_SINGLEKBL, SINGLEKBL_ENABLE)
    if trigger:
        ec_write(ADDR_TRIGGER, TRIGGER_BIT)   # 0x20 自清；保持 welcome 位为 0


def set_rgb(r: int, g: int, b: int, trigger: bool = True) -> None:
    """写 0..255 的 R/G/B 并点亮。

    ★ 关键：0x0769/6A/6B 接受的是 1..50 的「电平」，不是 0..255。
      必须经 to_level() 换算，否则写入被 EC 丢弃。

    点亮：写 trigger 位 0x20（自清）。**不要**留下 welcome 位 0x80，
    否则 EC 会持续跑旋转欢迎动画，覆盖掉静态色。
    """
    set_levels(to_level(r), to_level(g), to_level(b), trigger=trigger)


def get_levels() -> tuple:
    """返回 EC 里的原始电平 (r,g,b)，范围 1..50。"""
    return ec_read(ADDR_R), ec_read(ADDR_G), ec_read(ADDR_B)


def get_rgb() -> tuple:
    """返回 0..255 尺度的 (r,g,b)（由电平换算）。"""
    return from_levels(get_levels())


def off() -> None:
    """完全关闭键盘背光（全灭，无微光）。

    ★★ 实测确认（2026-10-16）：

        0x0769/6A/6B = 0/0/0   当前电平清零
        0x076C/6D/6E = 0/0/0   默认电平也清零  ← ★ 关键，不能只写前三个
        0x0767       = 0x20    触发（EC 只在收到 trigger 时刷新 LED）

    为什么两组电平都要写 0：EC 有周期任务会把「当前电平」同步为
    「默认电平」。只写当前电平的话，约 1 秒后就被默认电平覆盖回亮，
    表现为「灭了一下又亮」。两组同时写 0 才能稳定全灭（实测 >30 秒）。

    实测对照：
        · 只写电平 0，不触发        -> 灯不变（无效）
        · 只写当前电平 0 + 触发     -> 灭 1 秒后回跳
        · 当前 + 默认电平 0 + 触发  -> 完全熄灭，持久  ✔

    电平 0 与 1 的区别：0 = 全黑；1 = 最暗微光（暗处仍可见）。
    """
    set_levels(LEVEL_OFF, LEVEL_OFF, LEVEL_OFF,
               enable=True, trigger=True, defaults=True)


def on(rgb=None) -> tuple:
    """点亮，返回使用的颜色 (r,g,b)。

    颜色优先级：显式参数 > /run/kbdlight.last > EC 默认色 > 兜底青色。
    """
    if rgb is None:
        rgb = load_state()
    if rgb is None:
        dr, dg, db = (from_level(ec_read(ADDR_DEF_R)),
                      from_level(ec_read(ADDR_DEF_G)),
                      from_level(ec_read(ADDR_DEF_B)))
        rgb = (dr, dg, db) if (dr, dg, db) != (0, 0, 0) else (0x00, 0x32, 0x32)
    set_rgb(*rgb)
    save_state(rgb)
    return tuple(rgb)


def set_brightness(level_0_255: int) -> tuple:
    """按比例缩放亮度（保持色相），返回新颜色。

    亮度 0 = 关灯（电平全 0）。
    """
    if not 0 <= level_0_255 <= 255:
        raise ValueError("亮度范围 0-255")
    if level_0_255 == 0:
        off()
        return (0, 0, 0)
    r, g, b = get_rgb()
    mx = max(r, g, b)
    if mx == 0:
        off()
        return (0, 0, 0)
    scale = level_0_255 / mx
    nr, ng, nb = int(r * scale), int(g * scale), int(b * scale)
    set_rgb(nr, ng, nb)
    save_state((nr, ng, nb))
    return nr, ng, nb


def set_percent(pct: float) -> tuple:
    """按百分比直接设定亮度等级（1..50），不缩放色相。

    与 set_brightness 不同：这是直接改电平，颜色值会随之变化。
    """
    lvl = percent_to_level(pct)
    set_levels(lvl, lvl, lvl)
    rgb = from_levels((lvl, lvl, lvl))
    save_state(rgb)
    return rgb


def read_state() -> dict:
    """读回完整状态，供 GUI / 脚本使用。

    返回 dict:
        available   bool    acpi_call 是否可用
        levels      [r,g,b] EC 原始电平 1..50
        rgb         [r,g,b] 换算后的 0..255
        hex         str     "#RRGGBB"
        percent     float   0..100（由电平换算）
        lit         bool    是否点亮（电平 > 最小档）
        support     int     0x0766 原值
        rgb_supported bool  support bit2
        trigger     int     0x0767 原值
        welcome     bool    welcome 位是否置着（会导致旋转动画）
        singlekbl   int     0x078C 原值
        singlekbl_ok bool   是否等于 1
        defaults    [r,g,b] 默认色电平
        error       str|None 读失败时的错误信息
    """
    st = {
        "available": is_available(),
        "levels": None, "rgb": None, "hex": None, "percent": None, "lit": None,
        "support": None, "rgb_supported": None,
        "trigger": None, "welcome": None,
        "singlekbl": None, "singlekbl_ok": None,
        "defaults": None,
        "error": None,
    }
    if not st["available"]:
        st["error"] = "acpi_call 未加载（sudo modprobe acpi_call）"
        return st

    try:
        lr, lg, lb = get_levels()
        r, g, b = from_levels((lr, lg, lb))
        st["levels"] = [lr, lg, lb]
        st["rgb"] = [r, g, b]
        st["hex"] = rgb_to_hex((r, g, b))
        st["percent"] = level_to_percent(max(lr, lg, lb))
        st["lit"] = max(lr, lg, lb) > LEVEL_OFF

        sup = ec_read(ADDR_SUPPORT)
        st["support"] = sup
        st["rgb_supported"] = bool(sup & SUPPORT_BIT)

        trg = ec_read(ADDR_TRIGGER)
        st["trigger"] = trg
        st["welcome"] = bool(trg & WELCOME_BIT)

        sk = ec_read(ADDR_SINGLEKBL)
        st["singlekbl"] = sk
        st["singlekbl_ok"] = (sk == SINGLEKBL_ENABLE)

        st["defaults"] = [ec_read(ADDR_DEF_R), ec_read(ADDR_DEF_G),
                          ec_read(ADDR_DEF_B)]
    except KbdLightError as e:
        st["error"] = str(e)
    return st


# --------------------------------------------------------------------------
# 状态持久化 / 颜色解析
# --------------------------------------------------------------------------

def save_state(rgb) -> None:
    """保存 0..255 尺度的颜色（人类习惯），读取时再换算。"""
    try:
        with open(STATE_FILE, "w") as f:
            f.write("%02X%02X%02X" % tuple(rgb))
    except OSError:
        pass


def load_state():
    """读取上次保存的颜色，失败返回 None。"""
    try:
        with open(STATE_FILE) as f:
            s = f.read().strip()
        if re.fullmatch(r"[0-9A-Fa-f]{6}", s):
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except OSError:
        pass
    return None


def parse_hex_color(s: str) -> tuple:
    """'#f00' / 'f00' / '#ff0000' -> (r, g, b)。"""
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise ValueError(f"颜色格式错误: {s!r}（应为 RRGGBB，如 ff0000）")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def rgb_to_hex(rgb) -> str:
    """(r,g,b) -> '#RRGGBB'。"""
    return "#%02X%02X%02X" % tuple(int(x) & 0xFF for x in rgb)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _usage() -> None:
    print(__doc__)
    sys.exit(1)


def _print_read(state: dict, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(state, ensure_ascii=False))
        return

    if state["error"]:
        print(f"错误: {state['error']}")
        return

    lr, lg, lb = state["levels"]
    r, g, b = state["rgb"]
    print(f"键盘背光电平 = {lr} {lg} {lb}   (EC 范围 0..{LEVEL_MAX}，0=全灭)")
    print(f"换算成 0..255  = {r:02X} {g:02X} {b:02X}  ({state['hex']})")
    print(f"  SUPPORT 0x{ADDR_SUPPORT:04X} = 0x{state['support']:02X}"
          f"  (RGB支持位 bit2 = {'1(支持)' if state['rgb_supported'] else '0'})")
    print(f"  TRIGGER 0x{ADDR_TRIGGER:04X} = 0x{state['trigger']:02X}"
          f"  (bit7 welcome={1 if state['welcome'] else 0})")
    if state["welcome"]:
        print("  ⚠ welcome 位=1，EC 会跑旋转动画并覆盖静态色；"
              "设任意颜色即可清掉。")
    dr, dg, db = state["defaults"]
    print(f"  DEFAULT 0x076C-6E 电平 = {dr} {dg} {db}")
    print(f"  SINGLEKBL 0x{ADDR_SINGLEKBL:04X} = 0x{state['singlekbl']:02X}"
          + ("" if state["singlekbl_ok"]
             else "  ⚠ 应为 0x01，否则静态色不被接受"))
    if not state["lit"]:
        print("  (电平全 0 —— 键盘背光完全熄灭)")


def main(argv=None) -> int:
    """命令行入口。返回退出码。"""
    argv = list(sys.argv[1:] if argv is None else argv)

    # --json 可出现在任意位置
    as_json = False
    if "--json" in argv:
        argv.remove("--json")
        as_json = True

    if not argv:
        _usage()
    cmd = argv[0].lower()

    try:
        check_available()
    except KbdLightError as e:
        if as_json:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
        else:
            print(f"错误: {e}", file=sys.stderr)
        return 2

    try:
        if cmd == "read":
            _print_read(read_state(), as_json=as_json)

        elif cmd == "off":
            off()
            print("键盘背光已完全关闭（电平 0，无微光）。")

        elif cmd == "on":
            rgb = on()
            print(f"键盘背光已打开: {rgb_to_hex(rgb)}")

        elif cmd in ("brightness", "bri", "b"):
            if len(argv) < 2:
                print("用法: kbdlight brightness 0-255", file=sys.stderr)
                return 1
            level = int(argv[1], 0)
            if not 0 <= level <= 255:
                print("亮度范围 0-255（写 0 = 灭灯）", file=sys.stderr)
                return 1
            if level == 0:
                off()
                print("亮度 -> 0/255（已全灭）")
            else:
                nr, ng, nb = set_brightness(level)
                print(f"亮度 -> {level}/255  ({rgb_to_hex((nr, ng, nb))})")

        elif cmd in ("percent", "pct", "p"):
            if len(argv) < 2:
                print("用法: kbdlight percent 0-100", file=sys.stderr)
                return 1
            pct = float(argv[1])
            rgb = set_percent(pct)
            print(f"亮度 -> {pct:g}%  ({rgb_to_hex(rgb)})")

        elif cmd == "demo":
            for name, c in PALETTE[:7]:
                set_rgb(*c)
                print(f"  {rgb_to_hex(c)}  {name}")
                time.sleep(0.7)
            print("演示结束。")

        elif cmd in ("state", "--state"):
            _print_read(read_state(), as_json=True)

        else:
            rgb = parse_hex_color(cmd)
            set_rgb(*rgb)
            save_state(rgb)
            print(f"键盘背光 -> {rgb_to_hex(rgb)}")

    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    except KbdLightError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
