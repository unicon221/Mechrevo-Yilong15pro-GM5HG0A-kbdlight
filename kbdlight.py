#!/usr/bin/env python3
"""
kbdlight — 机械革命翼龙15Pro (Uniwill GM5HG0A) 键盘 RGB 背光控制

协议（逆向自厂商 ControlCenter GCUService.exe 的 LightingModel.EC_SPEC）
------------------------------------------------------------------------
键盘背光由 EC 寄存器控制。**关键：改完颜色后必须写触发字节点亮**，
否则寄存器值虽对，灯不亮。

    0x0766  SUPPORT_BYTE2   bit2(0x04) = 支持 RGB 键盘（只读位）
    0x0767  TRIGGER_BYTE    写 0x20 (bit5) = 触发/点亮键盘灯（自清位）
                            写 0x00          = 关闭键盘灯
                            0x80 (bit7)      = welcome 模式位（常驻，会导致旋转动画）
    0x0769  R   level (1-50)   ←★★ 不是 0-255！
    0x076A  G   level (1-50)
    0x076B  B   level (1-50)
    0x076C/6D/6E  DEFAULT R/G/B level (1-50)
    0x076F  MUSIC_NO
    0x078C  SINGLEKBL_ENABLE / AP_EC_LOGO_CONFIRM
    0x078E  SINGLEKBL_SUPPORTPOWER / SUPPORT_BYTE6

★★ 最重要的坑：RGBKB_LEVEL_R/G/B 是 1..50 的「电平」，不是 0..255 的颜色值！
   GCUService 常量（SingleZone 类，运行时反射得到）：
       RGB_LEVEL_SCALES         = 0x32 = 50
       RGB_LEVEL_MIN            = 1
       RGB_LEVEL_MAX            = 0x32 = 50
       RGB_VALUE_TO_LEVEL_RATIO = 5      (255 / 5 = 51 ~ 50)
   写入 >50 的值（例如 0xFF）会被 EC 直接忽略 —— 寄存器回读不变、灯不动。
   这就是「写了颜色但灯不亮/不变」的真正原因。
   必须把 0..255 的通道值换算： level = clamp(round(v / 255 * 50), 1, 50)

读写通道：ACPI 方法 \\_SB_.INOU.ECRR / ECRW（与内核 uniwill_laptop
驱动同一条通路），经 acpi_call 收发。地址是 16 位。

依赖
----
    sudo modprobe acpi_call

用法
----
    sudo kbdlight RRGGBB            # 设置颜色并点亮
    sudo kbdlight on                # 点亮（恢复默认色或上次颜色）
    sudo kbdlight off               # 关闭
    sudo kbdlight brightness 0-255  # 亮度（按比例缩放，保持色相）
    sudo kbdlight read              # 读当前状态与相关寄存器
    sudo kbdlight demo              # 循环演示颜色
"""

import os
import re
import sys
import time

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

TRIGGER_BIT = 0x20     # bit5 = EC_RGBKEYBOARD_TRIGGER_BIT（自清）
WELCOME_BIT = 0x80     # bit7 = EC_RGBKEYBOARD_WELCOME_ON_BIT（常驻，会跑旋转动画）
SUPPORT_BIT = 0x04     # bit2

# ★★ RGB 电平范围（GCUService LightingModel.SingleZone 常量）
LEVEL_MIN = 1
LEVEL_MAX = 50         # RGB_LEVEL_MAX = 0x32
LEVEL_SCALES = 50      # RGB_LEVEL_SCALES = 0x32
VALUE_TO_LEVEL_RATIO = 5   # RGB_VALUE_TO_LEVEL_RATIO


def to_level(v):
    """0..255 通道值 -> EC 的 1..50 电平。

    EC 只接受 1..50；超出范围的值会被丢弃（寄存器不变、灯不响应）。
    """
    v = max(0, min(255, int(v)))
    if v == 0:
        return 0                      # 0 = 该通道关灯，EC 接受
    lvl = int(round(v / 255.0 * LEVEL_SCALES))
    return max(LEVEL_MIN, min(LEVEL_MAX, lvl))


def from_level(lvl):
    """1..50 电平 -> 0..255 通道值（用于显示/回读）。"""
    lvl = max(0, min(LEVEL_MAX, int(lvl)))
    return int(round(lvl / float(LEVEL_SCALES) * 255))

STATE_FILE = "/run/kbdlight.last"   # 记录上次颜色，供 on 恢复


def _call(invocation):
    try:
        with open(ACPI_CALL, "w") as f:
            f.write(invocation)
    except OSError as e:
        sys.exit(f"无法写入 {ACPI_CALL}（需要 root 且已 modprobe acpi_call）: {e}")
    try:
        with open(ACPI_CALL, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    return raw.replace(b"\0", b"").decode("ascii", "replace").strip()


def ec_read(addr):
    out = _call(f"{EC_SCOPE}.ECRR 0x{addr:04X}")
    m = re.search(r"0x([0-9a-fA-F]+)", out or "")
    if not m:
        raise RuntimeError(f"读 EC 0x{addr:04X} 失败: {out!r}")
    return int(m.group(1), 16) & 0xFF


def ec_write(addr, value):
    out = _call(f"{EC_SCOPE}.ECRW 0x{addr:04X} 0x{value & 0xFF:02X}")
    if out.lower().startswith("error"):
        raise RuntimeError(f"写 EC 0x{addr:04X} 失败: {out!r}")


def set_rgb(r, g, b, trigger=True):
    """写 R/G/B 并点亮。

    ★ 关键：0x0769/6A/6B 接受的是 1..50 的「电平」，不是 0..255。
      必须经 to_level() 换算，否则写入被 EC 丢弃（这正是长期
      「寄存器写进去了但灯不变」的根因）。

    点亮：写 trigger 位 0x20 即可（自清）。**不要**留下 welcome 位 0x80，
    否则 EC 会持续跑旋转欢迎动画，覆盖掉静态色。
    """
    ec_write(ADDR_R, to_level(r))
    ec_write(ADDR_G, to_level(g))
    ec_write(ADDR_B, to_level(b))
    # 默认色也要保持合法电平（1..50）。残留的非法值（如 0xFF）会让
    # EC 的灯光任务进入异常分支，导致后续写入全部无效。
    ec_write(ADDR_DEF_R, to_level(r))
    ec_write(ADDR_DEF_G, to_level(g))
    ec_write(ADDR_DEF_B, to_level(b))
    if trigger:
        # ★ 0x078C 必须为 1，否则静态色不被 EC 接受（实测）。
        ec_write(ADDR_SINGLEKBL, SINGLEKBL_ENABLE)
        ec_write(ADDR_TRIGGER, TRIGGER_BIT)   # 0x20 自清；保持 welcome 位为 0


def get_rgb_levels():
    """返回 EC 里的原始电平 (r,g,b)，范围 1..50。"""
    return ec_read(ADDR_R), ec_read(ADDR_G), ec_read(ADDR_B)


def get_rgb():
    """返回 0..255 尺度的 (r,g,b)（由电平换算，仅作展示）。"""
    return tuple(from_level(x) for x in get_rgb_levels())


def save_state(rgb):
    """保存 0..255 尺度的颜色（人类习惯），读取时再换算。"""
    try:
        with open(STATE_FILE, "w") as f:
            f.write("%02X%02X%02X" % rgb)
    except OSError:
        pass


def load_state():
    try:
        with open(STATE_FILE) as f:
            s = f.read().strip()
        if re.fullmatch(r"[0-9A-Fa-f]{6}", s):
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except OSError:
        pass
    return None


def parse_hex_color(s):
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        sys.exit(f"颜色格式错误: {s!r}（应为 RRGGBB，如 ff0000）")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def usage():
    print(__doc__)
    sys.exit(1)


def main():
    if os.geteuid() != 0:
        sys.exit("请用 root 运行：sudo kbdlight ...")
    if not os.path.exists(ACPI_CALL):
        sys.exit(f"{ACPI_CALL} 不存在，请先： sudo modprobe acpi_call")

    argv = sys.argv[1:]
    if not argv:
        usage()
    cmd = argv[0].lower()

    if cmd == "read":
        lr, lg, lb = get_rgb_levels()
        r, g, b = (from_level(lr), from_level(lg), from_level(lb))
        sup = ec_read(ADDR_SUPPORT)
        trg = ec_read(ADDR_TRIGGER)
        print(f"键盘背光电平 = {lr} {lg} {lb}   (EC 范围 1..{LEVEL_MAX})")
        print(f"换算成 0..255  = {r:02X} {g:02X} {b:02X}  (#{r:02X}{g:02X}{b:02X})")
        print(f"  SUPPORT 0x{ADDR_SUPPORT:04X} = 0x{sup:02X}"
              f"  (RGB支持位 bit2 = {'1(支持)' if sup & SUPPORT_BIT else '0'})")
        print(f"  TRIGGER 0x{ADDR_TRIGGER:04X} = 0x{trg:02X}"
              f"  (bit5 触发={1 if trg & TRIGGER_BIT else 0}"
              f", bit7 welcome={1 if trg & WELCOME_BIT else 0})")
        if trg & WELCOME_BIT:
            print("  ⚠ welcome 位=1，EC 会跑旋转动画并覆盖静态色；"
                  "设任意颜色即可清掉。")
        dr, dg, db = (ec_read(ADDR_DEF_R), ec_read(ADDR_DEF_G), ec_read(ADDR_DEF_B))
        print(f"  DEFAULT 0x076C-6E 电平 = {dr} {dg} {db}")
        sk = ec_read(ADDR_SINGLEKBL)
        print(f"  SINGLEKBL 0x{ADDR_SINGLEKBL:04X} = 0x{sk:02X}"
              + ("" if sk == SINGLEKBL_ENABLE
                 else "  ⚠ 应为 0x01，否则静态色不被接受"))

    elif cmd == "off":
        # ★ 「灭灯」= 把三个电平都写到最低值 1（RGB_LEVEL_MIN）。
        # EC 的电平范围是 1..50，没有单独的「关灯」寄存器；
        # 写 1 就是实际不可见的灭灯，且写 0 会被 EC 拒绝。
        # （实测：0x0768<-0、0x078C<-0、0x078E<-0xE8 都不会灭灯。）
        ec_write(ADDR_R, LEVEL_MIN)
        ec_write(ADDR_G, LEVEL_MIN)
        ec_write(ADDR_B, LEVEL_MIN)
        ec_write(ADDR_SINGLEKBL, SINGLEKBL_ENABLE)
        ec_write(ADDR_TRIGGER, TRIGGER_BIT)
        print("键盘背光已关闭（电平降到最低）。")

    elif cmd == "on":
        rgb = load_state()
        if rgb is None:
            dr, dg, db = (from_level(ec_read(ADDR_DEF_R)),
                          from_level(ec_read(ADDR_DEF_G)),
                          from_level(ec_read(ADDR_DEF_B)))
            rgb = (dr, dg, db) if (dr, dg, db) != (0, 0, 0) else (0x00, 0x32, 0x32)
        set_rgb(*rgb)
        print(f"键盘背光已打开: #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")

    elif cmd in ("brightness", "bri", "b"):
        if len(argv) < 2:
            sys.exit("用法: kbdlight brightness 0-255")
        level = int(argv[1], 0)
        if not 0 <= level <= 255:
            sys.exit("亮度范围 0-255（写 0 = 灭灯）")
        r, g, b = get_rgb()
        mx = max(r, g, b)
        if mx == 0:
            sys.exit("当前是黑色的，先设一个颜色再调亮度。")
        scale = level / mx
        nr, ng, nb = int(r * scale), int(g * scale), int(b * scale)
        set_rgb(nr, ng, nb)
        save_state((nr, ng, nb))
        print(f"亮度 -> {level}/255  (#{nr:02X}{ng:02X}{nb:02X})")

    elif cmd == "demo":
        for c in ["ff0000", "00ff00", "0000ff", "ffff00", "00ffff",
                  "ff00ff", "ffffff"]:
            set_rgb(*parse_hex_color(c))
            print(f"  #{c}")
            time.sleep(0.7)
        print("演示结束。")

    else:
        rgb = parse_hex_color(cmd)
        set_rgb(*rgb)
        save_state(rgb)
        print(f"键盘背光 -> #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")


if __name__ == "__main__":
    main()
