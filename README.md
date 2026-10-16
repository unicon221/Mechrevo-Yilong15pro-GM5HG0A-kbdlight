# kbdlight — 机械革命翼龙15Pro 键盘 RGB 背光控制 (Linux)

在 Arch Linux 上原生控制 MECHREVO 翼龙15Pro（Uniwill GM5HG0A）键盘 RGB 背光。
无需 Windows、无需厂商驱动。

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
RGB_LEVEL_MIN            = 1     # 最暗的一档（仍可见微光）
RGB_LEVEL_MAX            = 0x32 = 50
RGB_VALUE_TO_LEVEL_RATIO = 5        # 255 / 5 = 51 ≈ 50
```

换算：`level = clamp(round(v / 255 * 50), 0, 50)`（`0` 保持 `0`）。

**`0` 和 `1` 是真的不同**：`0` = 完全熄灭；`1` = 最暗一档，暗环境里仍看得见。

**坑二：`0x078C` 必须 = `0x01`。**

```
0x078C = 0x02  → 静态色被忽略，键盘不亮
0x078C = 0x01  → 静态色生效  ✓
```

这是 A/B 对拍实验确认的（`02 → 01 → 02 → 01`，只有 `01` 时亮）。

### 正确的完整序列（六步）

```
0x078C <- 0x01        # 使能（必需，保持位）
0x0769 <- R 电平      # 0..50（0 = 该通道灭）
0x076A <- G 电平
0x076B <- B 电平
0x076C <- R 电平      # ★★ 默认电平必须同步，否则 1 秒后被 EC 覆盖回去
0x076D <- G 电平
0x076E <- B 电平
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

### `0x0768` 是状态寄存器，不是开关

接受 `0..3` 并保持（可写，不是被夹），但写它对 LED 输出**毫无影响**
（`2`/`3` 各保持 30 秒实测无反应）。它是 `RGBKB_PowerStatus` 的
「期望状态」，等厂商侧程序消费；而厂商侧代码在 GCUService 里被 ConfuserEx
清空了。**别用它开关灯。**

### ★★ 关灯 = 电平写 0，但必须同时写「默认电平」

**2026-10-16 修正**（推翻了之前「写 0 被拒绝」的旧结论）。真正的机制是：

> **EC 有周期任务，会把「当前电平」`0x0769/6A/6B` 同步为「默认电平」**
> **`0x076C/6D/6E`。**

所以：

| 你写什么 | 结果 |
|---|---|
| 只写当前电平 `0/0/0` | 灭约 1 秒 → **被默认电平覆盖回亮** |
| 当前 + 默认都写 `0/0/0`，再触发 | **持久全灭**（实测 >30 秒）✔ |
| 写 0 但**不触发** `0x0767=0x20` | 完全无变化 |

之前「写 0 被拒绝、回读保持旧值」是误判：我们是在写后约 1 秒读的，
读到的是**被恢复的默认值**，不是拒绝。

`off()` 已按此实现。只写当前电平时也只能得到「灭一下又亮」。

## 寄存器表（逆向自 GCUService.exe）

| 地址 | 名称 | 说明 |
|------|------|------|
| 0x0766 | EC_SUPPORT_BYTE2 | bit2 (0x04) = 支持 RGB 键盘（只读）|
| 0x0767 | EC_TRIGGER_BYTE | **bit5 (0x20)=触发（自清）**；bit4/6/7 (`0x10`/`0x40`/`0x80`)=保持位，静态色时须清零 |
| 0x0768 | STATUS_BYTE | 状态镜像（`RGBKB_PowerStatus` 期望值），接受 0..3，但写它不影响 LED |
| 0x0769 | RGBKB_LEVEL_R | R **电平 0–50**（同时决定亮度，0=灭）|
| 0x076A | RGBKB_LEVEL_G | G **电平 0–50** |
| 0x076B | RGBKB_LEVEL_B | B **电平 0–50** |
| 0x076C/6D/6E | RGBKB_LEVEL_DEFAULT_R/G/B | 默认色电平 **0–50**；★ EC 会周期性把当前电平同步为它 |
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
sudo kbdlight off                # 关灯（电平 0，完全熄灭）
sudo kbdlight brightness 120     # 亮度 0-255（按比例缩放，保持色相；0 = 关灯）
sudo kbdlight read               # 读当前 RGB 与相关寄存器
sudo kbdlight demo               # 循环演示颜色
```

已对当前用户加免密 sudo 规则（`/etc/sudoers.d/kbdlight`），日常 `sudo kbdlight ...`
无需输密码。可用 `kbdlight`（在 `/usr/local/bin`）。

## 文件

- `kbdlight.py` — 控制脚本（纯 Python 标准库）→ 安装为 `/usr/local/bin/kbdlight`
- `/etc/sudoers.d/kbdlight` — 免密规则
- `snapshots/` — 调查期间保存的 EC 快照（0x0400–0x07FF）

## 已知限制

- **`0x0751` 偶尔会自己变成 `0x40`（风扇满速）** —— 有别的程序在写它
  （可能与 `mechrevo-keyd` 有关）。`kbdlight read` 看不到它，需要直接读：
  `echo '\_SB_.INOU.ECRR 0x0751' | sudo tee /proc/acpi/call`。
  若为 `0x40`，写回 `0x00` 即可恢复。
- 键盘是**单色区（SingleZone）**：只支持静态颜色；亮度通过缩放 RGB 电平实现。
  **`off` 是真正的全灭**（当前 + 默认电平都写 `0` + 触发），无微光；
  注意：只写当前电平会在约 1 秒后被 EC 的周期任务恢复回亮。
- 本机 `0x0740 PROJECT_ID = 0x19`，**不在** Control Center 的项目枚举表里
  （最大 `0x11`）。所以厂商软件在这台机器上走的是兜底分支 —— 这也是为什么
  直接操作 EC 才是可行路线。
- 开机自检（BIOS POST）时键盘灯会亮一下，那是 EC 固件自己的初始化；
  进入系统后由本脚本接管。灯带（Lightbar，0x0748–0x074B）寄存器存在，
  但对普通单色键盘机型可能无效果。

## 更新记录

- **已解决：Linux 下静态固定颜色、全灭、亮度全部可用。** 三个关键坑：
  1. 电平范围 `0..50`（不是 0..255），且 `0` 才是真·全灭；
  2. `0x078C` 必须为 `0x01`，否则静态色被忽略；
  3. **`0x076C/6D/6E`（默认电平）必须与当前电平同步** —— EC 有周期任务会把
     当前电平拉回默认电平，只写 `0x0769/6A/6B` 会「灭一秒又亮」。
- 详细逆向过程见 `PROTOCOL.md`（含 PE 抓取流程、IL 反编译结论、
  寄存器全表、`0x0767` 逐位实测、`off` 候选逐一排除、恢复流程）。
