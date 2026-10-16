# Mechrevo-Yilong15pro-GM5HG0A-kbdlight

[中文](#中文) · [English](#english)

在 Arch Linux 上原生控制**机械革命 翼龙 15 Pro**（Uniwill **GM5HG0A** 模具）
的键盘 RGB 背光，**无需 Windows、无需厂商驱动、无需 WMI**。
通过 ACPI `\_SB_.INOU.ECRW`/`ECRR` 直接读写嵌入式控制器（EC）寄存器实现。

> **状态：全部功能已验证可用** —— 任意静态颜色、开灯、关灯、亮度调节。
> 本机实测：`kbdlight ff0000` / `kbdlight off` / `kbdlight on` / `kbdlight brightness 128`。

---

## English

Driver-free RGB keyboard backlight control for the **Mechrevo Yilong 15 Pro**
(Uniwill **GM5HG0A** chassis) on Linux. Writes the embedded controller (EC)
directly through the ACPI methods `\_SB_.INOU.ECRW` / `ECRR` — no Windows, no
vendor driver, no WMI.

All features are verified working on real hardware: arbitrary static colour,
on, off, and brightness. The full reverse-engineered protocol is documented in
[`PROTOCOL.md`](PROTOCOL.md).

**Quick start**

```bash
sudo modprobe acpi_call
sudo kbdlight ff0000      # set a colour and turn on
sudo kbdlight off         # turn off
sudo kbdlight on          # turn on, restoring the last colour
sudo kbdlight read        # show current state
```

---


## 中文

在 Arch Linux 上原生控制 **机械革命 翼龙 15 Pro**（Uniwill **GM5HG0A** 模具）
的键盘 RGB 背光。无需 Windows、无需厂商驱动。

## 安装

```bash
git clone https://github.com/unicon221/Mechrevo-Yilong15pro-GM5HG0A-kbdlight.git
cd Mechrevo-Yilong15pro-GM5HG0A-kbdlight
sudo install -m 755 kbdlight.py /usr/local/bin/kbdlight

# 可选：免密运行（sudo kbdlight ... 不再需要输密码）
echo "$USER ALL=(root) NOPASSWD: /usr/local/bin/kbdlight" \
  | sudo tee /etc/sudoers.d/kbdlight
sudo chmod 440 /etc/sudoers.d/kbdlight

# 可选：开机自动加载 acpi_call
echo acpi_call | sudo tee /etc/modules-load.d/acpi_call.conf
```

依赖只有一个：内核模块 **`acpi_call`**（多数发行版打包为 `acpi_call` 或
`acpi-call-dkms`）。不需要任何 Python 第三方库。

## 关键：协议

键盘背光**不走 USB HID**（`lsusb` 里没有 `048D` 的 ITE 设备），也**不走厂商 WMI**
（DSDT 的 `WMBC`/`WKBC` 在此固件上写命令无效）。真正通路是 **EC 寄存器 + 平台
ACPI 方法**：

```
读写通道:  \_SB_.INOU.ECRR <addr>          (读)
           \_SB_.INOU.ECRW <addr> <value>  (写)   ← 16 位地址
```

`\_SB_.INOU` 是平台设备 `INOU0000:00` 的 ACPI 对象，`ECRR`/`ECRW` 正是内核
`uniwill_laptop` 驱动内部调用的一对方法。经 `acpi_call` 即可在用户态使用。

### 最重要的坑（有两个，都踩过）

**坑一：`0x0769/6A/6B` 是「电平」1–50，不是 0–255 的颜色值。**

写入 >50 的值（例如 `0xFF`）会被 EC **静默丢弃** —— 寄存器回读不变、灯不动。
这是长期「寄存器写对了但灯不亮」的真正原因。

 GCUService 常量（`LightingModel.SingleZone`，未混淆）：

```
RGB_LEVEL_SCALES         = 0x32 = 50
RGB_LEVEL_MIN            = 1
RGB_LEVEL_MAX            = 0x32 = 50
RGB_VALUE_TO_LEVEL_RATIO = 5        # 255 / 5 = 51 ≈ 50
```

换算：`level = clamp(round(v / 255 * 50), 1, 50)`（`0` 保持 `0`）。

**坑二：`0x078C` 必须 = `0x01`。**

```
0x078C = 0x02  → 静态色被忽略，键盘不亮
0x078C = 0x01  → 静态色生效  ✓
```

这是 A/B 对拍实验确认的（`02 → 01 → 02 → 01`，只有 `01` 时亮）。

### 正确的完整序列（四步）

```
0x078C <- 0x01        # 使能（必需，保持位）
0x0769 <- R 电平      # 1..50
0x076A <- G 电平      # 1..50
0x076B <- B 电平      # 1..50
0x0767 <- 0x20        # 触发应用（自清）
```

### `0x0767` 位图（实测逐位）

| 写入 | 回读 | 含义 |
|------|------|------|
| `0x01` | `0x00` | 被消费（瞬态）|
| `0x02` | `0x00` | 被消费 = `LightBar_Trigger` |
| `0x04` | `0x00` | 被消费 |
| `0x08` | `0x00` | 被消费 |
| `0x10` | `0x10` | **保持** |
| `0x20` | `0x00` | 被消费 = `RGBKeybaord_Trigger`（应用位）|
| `0x40` | `0x40` | **保持** = `RGBLogo_Trigger` |
| `0x80` | `0x80` | **保持** = `RGBKeybaordWelcome_Trigger`（会跑旋转动画）|

**做静态色时 `0x10`/`0x40`/`0x80` 必须全部清零，只脉冲 `0x20`。**

注意 `0x0769/6A/6B` 同时是 `AP_EC_LOGO_R/G/B` —— 置上 logo trigger 后同一组寄存器会驱动 A 面 logo。

### `0x0768` 不是可靠的开关

只接受 `0..3`（写 `4`/`5` 会被夹回 `0`/`1`），而且会与实际亮灭**不同步**
（实测键盘亮着时它读 `0x00`，写 `0x00` 也不灭灯）。**不要用它开关灯。**

### 不要把 0 写进电平寄存器

`RGB_LEVEL_MIN = 1`，写 `0x00` 被拒绝，回读保持旧值。

## 寄存器表（逆向自 GCUService.exe）

| 地址 | 名称 | 说明 |
|------|------|------|
| 0x0766 | EC_SUPPORT_BYTE2 | bit2 (0x04) = 支持 RGB 键盘（只读）|
| 0x0767 | EC_TRIGGER_BYTE | **bit5 (0x20)=触发（自清）**；bit4/6/7 (`0x10`/`0x40`/`0x80`)=保持位，静态色时须清零 |
| 0x0768 | STATUS_BYTE | 只接受 0..3，与实际亮灭不同步，勿用作开关 |
| 0x0769 | RGBKB_LEVEL_R | R **电平 1–50**（同时决定亮度）|
| 0x076A | RGBKB_LEVEL_G | G **电平 1–50** |
| 0x076B | RGBKB_LEVEL_B | B **电平 1–50** |
| 0x076C/6D/6E | RGBKB_LEVEL_DEFAULT_R/G/B | 默认色，**同样 1–50** |
| 0x076F | RGBKB_MUSIC_NO | 音乐律动序号 |
| 0x0740 | PROJECT_ID_BYTE | 项目号（本机 `0x19`）|
| 0x0741 | AP_OEM_BYTE | OEM 字节 |
| 0x0748 | LIGHTBAR_CONTROL_BYTE | 灯条控制（非键盘背光）|
| 0x0749/4A/4B | RED/GREEN/BLUEBAR_CONTROL_BYTE | 灯条 R/G/B 控制 |
| 0x0751 | MANUAL_FAN_CTRL | ⚠ **风扇手动控制，务必保持 0x00**（写 `0x40` = 满速）|
| 0x075B/75C | MAIN_FAN_L/R_DUTY | ⚠ 风扇占空比，**不要写** |
| 0x078C | SINGLEKBL_ENABLE / LOGO_CONFIRM | **必须 = 0x01**，否则静态色无效 |
| 0x078E | SINGLEKBL_SUPPORTPOWER / SUPPORT_BYTE6 | 支持位（本机 `0xEC`）|

bit 常量：`SUPPORT_BIT=0x04`、`TRIGGER_BIT=0x20`、`WELCOME_BIT=0x80`。

其他一次性的通知口（写完即清零，不存状态）：
`0x00B1` (LEVEL_DOWN)、`0x00B2` (LEVEL_UP)、`0x00B4` (SINGLEKBL_LEVEL_CHG)、
`0x00F0` (LEVEL_UPDATE)、`0x00B6` (ChinaMode_Change)、`0x00B9` (CIRCLE_UP)。

## 用法

```bash
sudo modprobe acpi_call          # 通常已自动加载

sudo kbdlight ff0000             # 设为红色并点亮
sudo kbdlight 1e90ff             # 道奇蓝
sudo kbdlight on                 # 点亮（恢复上次颜色/默认色）
sudo kbdlight off                # 关灯（电平降到最低）
sudo kbdlight brightness 120     # 亮度 0-255（按比例缩放，保持色相；0 = 关灯）
sudo kbdlight read               # 读当前 RGB 与相关寄存器
sudo kbdlight demo               # 循环演示颜色
```

配了上面的 sudoers 规则后，日常 `sudo kbdlight ...` 不再需要输密码。

## 文件

- `kbdlight.py` — 控制脚本（纯 Python 标准库，约 300 行）
- `PROTOCOL.md` — 完整逆向协议：寄存器表、位定义、枚举、
  以及「为什么之前一直失败」的三个坑
- `LICENSE` — MIT

## 已知限制

- **`0x0751` 偶尔会自己变成 `0x40`（风扇满速）** —— 有别的程序在写它
  （可能与 `mechrevo-keyd` 有关）。`kbdlight read` 看不到它，需要直接读：
  `echo '\_SB_.INOU.ECRR 0x0751' | sudo tee /proc/acpi/call`。
  若为 `0x40`，写回 `0x00` 即可恢复。
- 键盘是**单色区（SingleZone）**：只支持静态颜色；亮度通过缩放 RGB 电平实现。
  `off` 是把电平降到最低（`1/1/1`），不是物理断电 —— 肉眼看起来就是灭的。
- 本机 `0x0740 PROJECT_ID = 0x19`，**不在** Control Center 的项目枚举表里
  （最大 `0x11`）。所以厂商软件在这台机器上走的是兜底分支 —— 这也是为什么
  直接操作 EC 才是可行路线。
- 开机自检（BIOS POST）时键盘灯会亮一下，那是 EC 固件自己的初始化；
  进入系统后由本脚本接管。灯带（Lightbar，0x0748–0x074B）寄存器存在，
  但对普通单色键盘机型可能无效果。

## 更新记录

- **已解决：Linux 下静态固定颜色、开关、亮度全部可用。** 根因是两个坑
  （电平范围 1–50、`0x078C` 必须为 1），外加「没有关灯寄存器，`off` = 电平 1」。
- 详细逆向过程见 `PROTOCOL.md`（寄存器全表、`0x0767` 逐位实测、
  `off` 候选逐一排除、恢复流程、厂商软件协议分析）。

## 适用范围 / 免责

本项目的寄存器地址与位定义来自对**本机**（翼龙 15 Pro，GM5HG0A）
的实测与厂商驱动的公开元数据分析。**不同模具/批次的 EC 固件可能不同**，
在别的机型上直接写 EC 有风险（尤其是 `0x0751` 风扇控制、
`0x075B/75C` 风扇占空比 —— 请勿触碰）。

本项目与机械革命（Mechrevo）无关联，仅供互操作性研究使用。

