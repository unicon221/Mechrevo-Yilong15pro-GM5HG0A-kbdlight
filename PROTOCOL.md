# Mechrevo Control Center — Keyboard RGB 控制协议（完整逆向）

> 目标机型: MECHREVO 翼龙15Pro (GM5HG0A)，Uniwill EC。
> 版本: ControlCenter 5.56.60.3 Mechrevo GX。

## 1. 架构全景

```
  ┌─────────────────────────────────────────────────────────┐
  │  UWP/WinUI3 应用 "CCU.WinUI"  (CCUWinUI.exe)            │
  │  .NET 8 self-contained, FullTrustApplication            │
  │  ── 来自 PreinstallKit/CCU.WinUI.msix (141MB, 可侧载)   │
  └───────────────┬─────────────────────────────────────────┘
                  │ MQTT publish  topic="Keyboard/Ctrl"
                  │ payload = MyKeyBoard JSON (System.Text.Json)
                  ▼
  ┌─────────────────────────────────────────────────────────┐
  │  GCUBridge.exe  (Windows 服务 "GCUBridge")              │
  │  = MQTT broker (MQTTnet), 监听 127.0.0.1:13688 (0x3578) │
  │  纯转发/鉴权, 不做业务                                   │
  └───────────────┬─────────────────────────────────────────┘
                  │ MQTT subscribe topic="Keyboard/Ctrl"
                  ▼
  ┌─────────────────────────────────────────────────────────┐
  │  GCUService.exe  (Costura 单文件, 内嵌全部托管依赖)      │
  │  ── LightingModel.LM_EC_RGB : ILM_RGBKB                 │
  │  ── MyECIO.MyEcCtrl.Write(ACPI_name, addr, data)        │
  └───────────────┬─────────────────────────────────────────┘
                  │ DeviceIoControl
                  ▼
  ┌─────────────────────────────────────────────────────────┐
  │  ACPIDriverDll.dll → \\.\ACPIDriver                    │
  │  IOCTL 0x9C40A48C (write) / 0x9C40A488 (read)           │
  └───────────────┬─────────────────────────────────────────┘
                  ▼
  ┌─────────────────────────────────────────────────────────┐
  │  UWACPIDriver.sys  →  ACPI \_SB_.INOU.ECRW/ECRR         │
  └─────────────────────────────────────────────────────────┘
```

## 2. MQTT

| 项 | 值 |
|---|---|
| Broker | `GCUBridge.exe` (服务名 `GCUBridge`) |
| 地址 | `127.0.0.1` |
| 端口 | `13688` (`0x3578`) |
| 库 | MQTTnet (broker) / M2Mqtt (client in UI) |
| 加密密钥 | `GamingCenterTest5566`（凭据字典 Decrypt_Key） |
| 连接校验 | `ValidatingMqttClients()`，用字典 `c_u` / `u_psw` |

### Topic 一览（键盘相关）

| Topic | 方向 | 说明 |
|---|---|---|
| `Keyboard/Ctrl` | UI → Service | 控制命令（本文件重点） |
| `Keyboard/Status` | Service → UI | 状态回报 |
| `HidLightbar/Ctrl` / `HidLightbar/Status` | | HID 灯条 |
| `MyRgbLightbar/Control` / `Status` | | EC 灯条 |
| `KeyboardSingleZone/Status` | | 单区键盘状态 |
| `HidLightbar_Logo/Status`, `HidLightbar_Hinge/Status`, `HidLightbar_Sync/Status` | | 灯条子区 |

## 3. `Keyboard/Ctrl` 消息 = `MyKeyBoard` (JSON)

来自 `CCUWinUI.dll` → `WinUIGallery.Models.MyKeyBoard`，序列化用 `Helpers.Json::Stringify`。

```jsonc
{
  "MqttID":           null,        // string
  "function":         "SetEffectALL", // string  ← 命令名, 见下表
  "mode":             "Lighting",  // string  ← RGBKB_Mode
  "effect":           "Single",    // string  ← RGBKB_Effect  ← ★静态色=Single
  "light":            "4",         // string  ← 亮度 (字符串!)
  "speed":            "0",         // string  ← 速度 (字符串!)
  "direction":        "None",      // string  ← RGBKB_Direction
  "nv_save":          "SAVE",      // string  ← RGBKB_NV_SAVE
  "color": {                       // object, 见下
    "isCircular":     false,       // ★静态=false, 轮转=true
    "ColorBlocks":    126,         // int32  颜色块数
    "ColorBuffer":    [ { "ID":0, "R":255, "G":0, "B":0 }, ... ]
  },
  "backgroundcolor":  0,           // int32
  "alphabet":         "",          // string
  "solution":         1,           // int32  ← RGBKB_Solution (1=EC)
  "level":            0,           // int32
  "powerstatus":      0,           // int32  ← RGBKB_PowerStatus
  "type":             0,           // int32  ← RGBKB_Type
  "MonochromeIndex":  null,        // string
  "ManualIndex1":     null,        // string  (1..6)
  "ManualInterval":   null,
  "BreathingIndex":   null,
  "DefaultData":      null,
  "AuroraSwitch":     false
}
```

### `function` 命令名（`MyKeyBoardCmd`）

| 值 | 说明 |
|---|---|
| `Init` | 初始化（UI 启动时；实际 topic 用 `keyboard/ctrl` 小写） |
| `DeInit` | 反初始化 |
| `SetPower` | 开关灯（配 `powerstatus`） |
| `SetEffectALL` | **设置完整效果**（mode+effect+light+speed+direction+color+save）← 主命令 |
| `SetColor` | 只改颜色 |
| `SetLightingLevel` | 改亮度 |
| `SetAurora` | 氛围灯 |
| `SaveLightingLevel` | 保存亮度 |

特殊：`{"GETSTATUS"}`（匿名类型 `<>f__AnonymousType0<string>`）→ 查询状态。

## 4. 枚举（`CCUWinUI.dll` / `GCUService.exe` 完全一致）

### RGBKB_Mode
```
NA=0, Lighting=1, Welcome=2, Night=3
```

### RGBKB_Effect  ★核心
```
Single      = 0    ← ★★★ 静态单色 (用户要的!)
Breathing   = 1
Wave        = 2
Reactive    = 3
Rainbow     = 4    ← 当前默认 (轮转彩虹)
Ripple      = 5
Raindrop    = 6
Marquee     = 7
Impact      = 8
Spark       = 9
Aurora      = 10
Music       = 11
UserMode    = 12
Gaming      = 13
Flash       = 14
Mix         = 15
Thinking    = 16
Devour      = 17
BatteryPercent = 18
Manual      = 19
ColorfulWave= 20
Dawn        = 21
ColorMarquee= 22
Twinkling   = 23
Sine        = 24
Interlace   = 25
Diagonal    = 26
```

### RGBKB_Direction
```
None        = 0xFFFFFFFF  (-1)
LeftRight   = 0
RightLeft   = 1
DownUp      = 2
UpDown      = 3
OnKeyPressed= 4
Sync        = 5
```

### RGBKB_NV_SAVE
```
NOT_SAVE = 0
SAVE     = 1
```

### RGBKB_Solution
```
UNKNOWN=0, EC=1, ITE=2      → 本机 = EC
```

### RGBKB_PowerStatus
```
Off=0, On=1, Lighting_off=2, Lighting_on=3, Welcome_off=4, Welcome_on=5
```

### RGBKB_Type
```
Normal=0, SingleZone=1, FourZone=2, FourZoneSingleColor=3, ...
MEZone_Lighbar=0x10
```

### RGB_S
```csharp
uint32 ID; int32 R; int32 G; int32 B;
```

## 5. 静态单色：确切做法

用户在 UI 里选 "Single"（静态）+ 一个颜色时，UI 构造：

```jsonc
{
  "function": "SetEffectALL",
  "mode":     "Lighting",
  "effect":   "Single",          // ★
  "light":    "4",
  "speed":    "0",               // ★ 静态 = 速度 0
  "direction":"None",
  "nv_save":  "SAVE",
  "color": {
    "isCircular": false,         // ★ 静态
    "ColorBlocks": <N>,
    "ColorBuffer": [ R,G,B ... ]
  },
  "solution": 1,
  "level": 0
}
```
topic = `Keyboard/Ctrl`。

## 6. 配置文件（UI 侧）

`appsettings.json` → `UWPCustomSettings`：

| key | 说明 |
|---|---|
| `singlezone_Keyboard` | 单区键盘效果索引，`"0"`=Single |
| `mezone_Keyboard` | 多区键盘效果名，如 `"Rainbow"` |
| `mezone_Keyboard_Light` | 亮度 `"3"` |
| `mezone_Keyboard_Speed` | 速度 `"2"` |
| `colorbuffer1` | 颜色缓冲（null / 串） |

## 7. EC 层（Linux 直接控制）

ACPI 方法: `\_SB_.INOU.ECRR <addr04X>` / `\_SB_.INOU.ECRW <addr04X> <val02X>`

| 地址 | 名称 | 说明 |
|---|---|---|
| `0x0760` | mode | 默认 0x0F |
| `0x0765` | SUPPORT_BYTE1 | 0xa1 |
| `0x0766` | SUPPORT_BYTE2 | bit2=0x04 → RGB KB 支持 |
| `0x0767` | **TRIGGER_BYTE** | **自清零**：`0x20`=键盘,`0x80`=欢迎,`0x40`=logo,`0x02`=灯条 |
| `0x0768` | **STATUS_BYTE** | 可写持久，= RGBKB_PowerStatus |
| `0x0769/6A/6B` | RGB / LOGO LEVEL R/G/B | |
| `0x076C/6D/6E` | RGB DEFAULT R/G/B | |
| `0x076F` | MUSIC_NO | |
| `0x0748` | LIGHTBAR_CONTROL_BYTE | ⚠不要碰 fan 相关 |
| `0x078C` | SINGLEKBL / EC_LOGO_CONFIRM | |

**EC 固件内部运行动画**，UI 只发送完整效果定义（effect + 颜色 + 速度）。

## 8. 工具

- UI: `CCUWinUI.exe`（来自 msix，全信任，可 `ccuwinui:` 协议启动）
- Broker: `GCUBridge.exe`（服务，端口 13688）
- 后端: `GCUService.exe`（写 EC）
- 注册表持久化: `HKLM\SOFTWARE\OEM\GamingCenter2\RGBKeyboard` → `LastEffect`, `LastWelcomeEffect`

## 9. Linux 侧方案（结论）

经过完整验证，**唯一可行的是方案 B：直接写 EC 寄存器**。

- ~~方案 A：Wine + .NET 跑 MQTT 客户端~~ —— `GCUService.exe` 被 ConfuserEx
  加壳，只含 Windows-JIT 专属 IL，Wine/Mono 无法执行（详见下文）。
- ~~方案 C：在 Windows 环境下运行厂商 Control Center 抓取~~ —— 可运行，但本机
  `PROJECT_ID=0x19` 不在厂商支持的机型表里，走兜底分支，抓到的写入序列无效。
- **方案 B：直接 EC 写** ✔ —— 本文档第 7 节 + 后面的「BREAKTHROUGH」章节
  就是完整协议。Linux 下通过 `\_SB_.INOU.ECRR/ECRW` 直接读写，
  无需任何 Windows 组件。

---

## What the reflection host *did* recover (valuable!)

Reflection over the *unencrypted metadata* works fine and yielded the
authoritative API + struct layouts.

### LM_Manager (LightingModel)

```csharp
bool LM_Init(string DefaultTool = null);
bool LB_Init(string DefaultTool = null);
bool LM_SetPower(RGBKB_PowerStatus s);
bool LM_SetEffectALL(RGBKB_Mode mode, RGBKB_Effect effect,
                     uint light, uint speed, RGBKB_Direction dir,
                     RGBKB_Color color, RGBKB_NV_SAVE save,
                     int backgroundcolor = 0, string alphabet = null);
bool LM_SetColor(RGBKB_Mode mode, RGBKB_Effect effect, RGBKB_Color color);
bool LM_SetLightingLevel(uint level);
bool LM_SaveLightingLevel(uint level);
bool LM_GetEffect(RGBKB_Mode mode, out RGBKB_Effect effect);
bool LM_GetLightingLevel(out uint level);
string LM_GetFirmwareVersion();
```
Fields: `bool m_bInitStatus; ILM_RGBKB m_ILM_RGBKB; LM_ITE_RGB m_LM_ITE_RGB;
LM_EC_RGB m_LM_EC_RGB; RGBKB_Solution m_KB_Solution; RGBKB_Type m_KB_Type;`

### RGBKB_Color / RGB_S  (exact marshalling layout)

```
RGBKB_Color  size 16 : +0x00 bool  isCircular
                       +0x04 uint  ColorBlocks
                       +0x08 RGB_S[] ColorBuffer
RGB_S        size  8 : +0x00 uint ID   (uint32, NOT byte)
                       +0x04 byte R
                       +0x05 byte G
                       +0x06 byte B
```

### SAVE_EC_LIGHTING_EFFECT_DATA (size 64)

```
+0x00 byte  save_effect
+0x04 bool  bSaved
+0x08 int   MonochromeIndex
+0x0c..0x20 int ManualIndex1..6
+0x24 int   ManualInterval
+0x28 int   BreathingIndex
+0x30 RGBKB_Color UserDefineColor
```

### Full enum tables (authoritative, from runtime reflection)

`RGBKB_Effect`: Single=0 Breathing=1 Wave=2 Reactive=3 Rainbow=4 Ripple=5
Raindrop=6 Neon=7 Marquee=8 Stack=9 Impact=10 Spark=11 Aurora=12 Music=13
UserMode=14 Gaming=15 Flash=16 Mix=17 RippleO=18 UnKnown=19 Alphabet=20
StarHitting=21 StarSpark=22 Thinking=23 Manual=24 BatteryPercent=25
ColorfulWave=26 Dawn=27 ColorMarquee=28 Twinkling=29 Sine=30 Interlace=31
Diagonal=32

`RGBKB_Mode`: NA=0 Lighting=1 Welcome=2 Night=3
`RGBKB_Direction`: LeftRight=0 RightLeft=1 DownUp=2 UpDown=3 OnKeyPressed=4
Sync=5 None=-1
`RGBKB_NV_SAVE`: NOT_SAVE=0 SAVE=1
`RGBKB_PowerStatus`: Off=0 On=1 Lighting_off=2 Lighting_on=3 Welcome_off=4
Welcome_on=5
`RGBKB_Solution`: UNKNOWN=0 EC=1 ITE=2
`RGBKB_Type`: Normal=0 SingleZone=1 FourZone=2 FourZoneSingleColor=3
MEZone_1st=4 MEZone_2nd_101=5 MEZone_2nd_102=6 MEZone_3p1nd_101=7
MEZone_3p1nd_102=8 MEZone_3p1nd_103=9 MEZone_3p1nd_104=10
MEZone_2p1nd_85=11 MEZone_2p1nd_86=12 MEZone_2p1nd_87=13 MEZone_2p1nd_88=14
MEZone_2p2nd=15 MEZone_Lighbar=16 MEZone_2p2nd_97=17 MEZone_2p2nd_98=18
MEZone_2p2nd_99=19 MEZone_2p2nd_100=20 MEZone_3nd_98=21 MEZone_3nd_99=22
MEZone_Lighbar2=23 MEZone_Lighbar3=24 MEZone_Lighbar4=25
MEZone_Lighbar4_logo=26 MEZone_Lighbar4_hinge=27 MEZone_Lighbar4_sync=28

### MQTT topics (MyControlCenter.Topic)

`Keyboard/Ctrl` (RGBKeyboard_Control), `Keyboard/Status`, `EC_Control`,
`EC_Status`, `Fan_Control`, `Fan_Status`, `Setting_Control`,
`Service_Control`, `RGBLB_Control`, `HIDRGBLightbar_Control`, ...
Publish path: `WinUIGallery.Helpers.TopicSendToServerQueue::SendTopicToServer`
Payload class: `WinUIGallery.Models.MyKeyBoard` — **all fields are strings**
except `int backgroundcolor, solution, level, powerstatus, type` and
`bool AuroraSwitch`; `color` is `WinUIGallery.Models.color`
(`bool isCircular; int ColorBlocks; RGB_S[] ColorBuffer`).

`MyKeyBoardCmd.SetEffectALL` is the command verb for a full effect change.

### UI effect-index → firmware effect-number map

(from `LightViewModel::InitalizeKeyboardEffect`, `EffecMapping` dict)

```
0->1  1->2  2->3  3->4  4->5  5->6  7->9  6->10 10->14 9->17
13->21 12->51 11->34 20->52 14->18 15->19 16->33 17->13
```

### IOCTL constants (confirmed, MyECIO.AcpiCtrl)

```
GPD_TYPE                 = 0x00009C40
IOCTL_GPD_ACPI_ECREAD    = 0x9C40A488   // in {u32 addr}
IOCTL_GPD_ACPI_ECWRITE   = 0x9C40A48C   // in {u32 addr, u32 data}
IOCTL_GPD_ACPI_CMREAD    = 0x9C40A480
IOCTL_GPD_ACPI_CMWRITE   = 0x9C40A484
IOCTL_GPD_ACPI_SMAPCTABLE= 0x9C40A500
IOCTL_GPD_ACPI_CUSTOMCTL = 0x9C40A504
```
EC read/write entry points: `MyECIO.MyEcCtrl::Read/Write(string name, ushort addr, byte data)`
→ `MyECIO.AcpiCtrl::Read/Write` → `DeviceIoControl("\\.\ACPIDriver", ...)`.

## Consequence

ConfuserEx only encrypts **method bodies**; metadata (type names, fields,
literals, enum values, struct layout) stays intact and can be read statically
or via reflection.  Everything above was recovered that way, and it was enough
to identify the EC registers and bit meanings that the Linux implementation
uses — no Windows code needs to run.

The method bodies themselves are only needed if you want to know the exact
order in which the vendor driver pokes registers; the results in this document
were obtained empirically instead, by writing registers on a real machine and
observing the keyboard.

---

# ★★★ BREAKTHROUGH — RGBKB_LEVEL registers are LEVELS (1..50), not 0..255 ★★★

## The bug that cost us everything

`0x0769` / `0x076A` / `0x076B` (`RGBKB_LEVEL_R/G/B`) are **not** 0..255 colour
channels.  They are **brightness levels in the range 1..50**.

Evidence, straight out of the unobfuscated constant table of
`MyControlCenter.MyRgbKeyboard.SingleZone` (runtime reflection on
`GCUService.exe`):

```
.field static assembly literal int32 RGB_LEVEL_SCALES = int32(0x00000032)   // 50
.field static assembly literal int32 RGB_LEVEL_MIN    = int32(0x00000001)   //  1
.field static assembly literal int32 RGB_LEVEL_MAX    = int32(0x00000032)   // 50
.field static assembly literal int32 RGB_VALUE_TO_LEVEL_RATIO = int32(5)    // 255/5 = 51
.field static assembly literal int32 MONOCHROME_COLOR_INDEX_MIN = int32(1)
.field static assembly literal int32 MONOCHROME_COLOR_INDEX_MAX = int32(0x1E) // 30
.field static assembly literal int32 MANUAL_COLORS_COUNT = int32(6)
```

**Writing anything > 50 is silently discarded by the EC.**  The register
read-back keeps its old value and the LEDs do not change.  That is exactly
what we observed for many rounds: `0x0769 <- 0xFF` "succeeded" (no error),
the trace showed `0769 00 -> FF`, but the keyboard stayed on its animation.

The fix is a one-liner:

```python
level = clamp(round(v / 255.0 * 50.0), 1, 50)   # 0 stays 0 (= channel off)
```

Verification on the real machine:

```
$ sudo kbdlight ff0000      -> levels  50  0  0   = pure red     ✓ visible
$ sudo kbdlight 00ff00      -> levels   0 50  0   = pure green   ✓ visible
$ sudo kbdlight 0000ff      -> levels   0  0 50   = pure blue    ✓ visible
$ sudo kbdlight ffffff      -> levels  50 50 50   = white         ✓ visible
$ sudo kbdlight ff6600      -> levels  50 20  0   = orange        ✓ visible
$ sudo kbdlight 8000ff      -> levels  25  0 50   = violet        ✓ visible
$ sudo kbdlight 00ffff      -> levels   0 50 50   = cyan          ✓ visible
$ sudo kbdlight brightness 128 -> 50->25       = dimmed red      ✓ visible
```

## The welcome bit is a trap

`0x0767` bit7 (`0x80`) is `EC_RGBKEYBOARD_WELCOME_ON_BIT`.  It is a
**sticky** bit (unlike bit5 `0x20` which the EC consumes immediately).

* `0x0767 <- 0x80`  -> keyboard lights up and runs a **rotating rainbow
  welcome animation** that **overrides any static colour**.
* `0x0767 <- 0xA0`  -> reads back as `0x80`; the `0x20` is consumed, the
  animation keeps running.
* `0x0767 <- 0x20`  -> reads back as `0x00`; applies the current state once.

So the correct static-colour sequence is simply:

```
write 0x0769 = level_r        (1..50)
write 0x076A = level_g        (1..50)
write 0x076B = level_b        (1..50)
write 0x0767 = 0x00           (make sure the welcome bit is clear!)
write 0x0767 = 0x20           (trigger apply; self-clearing)
```

**Never leave `0x80` set** if you want a solid colour.

## Bonus registers discovered from the same constant table

The generic `ADDR_*` table lives in another obfuscated class; the keyboard
specific EC addresses are in `HIDKeyboard` (base class of every keyboard
type):

```
EC_RGBKBBKL_LEVEL_UPDATE = 0x00F0
EC_RGBKBBKL_LEVEL_DOWN   = 0x00B1
EC_RGBKBBKL_LEVEL_UP     = 0x00B2
EC_SINGLEKBL_LEVEL_CHG   = 0x00B4
EC_ChinaMode_Change      = 0x00B6
EC_RGBKBBKL_CIRCLE_UP    = 0x00B9
```

All read back as `0x00` on this machine (event/notification ports, not
storage).

Full keyboard-relevant map (from the `ADDR_*` literal table):

```
ADDR_TRIGGER_BYTE            = 0x0767
ADDR_TRIGGER_BYTE2           = 0x075D
ADDR_STAUTS_BYTE             = 0x0768
ADDR_RGBKB_LEVEL_R/G/B       = 0x0769 / 0x076A / 0x076B   (1..50)
ADDR_RGBKB_LEVEL_DEFAULT_R/G/B = 0x076C / 0x076D / 0x076E (1..50)
ADDR_RGBKB_MUSIC_NO          = 0x076F
ADDR_AP_EC_LOGO_R/G/B        = 0x0769 / 0x076A / 0x076B   (same regs, logo role)
ADDR_SINGLEKBL_ENABLE        = 0x078C   (a.k.a. AP_OEM_BYTE2 / AP_EC_LOGO_CONFIRM)
ADDR_SINGLEKBL_SUPPORTPOWER  = 0x078E   (a.k.a. SUPPORT_BYTE6)
ADDR_LIGHTBAR_CONTROL_BYTE   = 0x0748
ADDR_REDBAR_CONTROL_BYTE     = 0x0749
ADDR_GREENBAR_CONTROL_BYTE   = 0x074A
ADDR_BLUEBAR_CONTROL_BYTE    = 0x074B
ADDR_AP_OEM_SingleZone       = 0x0D00
ADDR_SUPPORT_BYTE1           = 0x0765
ADDR_SUPPORT_BYTE2           = 0x0766   (bit2 = 0x04 RGB supported)
ADDR_PROJECT_ID_BYTE         = 0x0740
ADDR_AP_OEM_BYTE             = 0x0741
```

## Red herrings — do not touch these

`0x075B` and `0x075C` are **NOT** lighting registers.  They are:

```
ADDR_EC_MAIN_FAN_L_DUTY_BYTE = 0x075B
ADDR_EC_MAIN_FAN_R_DUTY_BYTE = 0x075C
```

A long register trace showed them oscillating between `0x3C` and `0x47`
roughly every 300 ms for over two minutes, perfectly correlated with the
temperature registers.  That was **the fans tracking temperature**, not a
keyboard animation.  Don't be misled again.

Also note `ADDR_CPU_VRM_CURRENT_LIMIT_BYTE = 0x0753` and
`ADDR_CPU_VRM_MAXI_CURRENT_LIMIT_BYTE = 0x0754` sit right next to the RGB
block — leave them alone.

## Keyboard type dispatch (for future work)

`MyControlCenter.MyRgbKeyboard.HIDKeyboard` is the base class; the factory
`HIDKeyboardFactory.CreateHIDDevice(LM_Manager, RGBKB_Type, bool)` picks:

```
SingleZone                    <- this machine (single-zone, EC/logo regs)
FourZoneKeyboard
FourZoneSingleColorKeyboard
_2p1ndkeyboard / _KC / _QC
_2p2ndkeyboard
_3ndKeyboard
AlphabetEffect
HIDLightbar / 2 / 3 / 4 / 4_sync / 4_hinge / 4_logo
```

`HIDKeyboard` holds `_KeyboardControl` of type `LightingModel.LM_ITE_RGB`
and `m_hidkeyboad` for the HID transport, plus `_effect_data` of type
`SAVE_EC_LIGHTING_EFFECT_DATA`:

```
struct SAVE_EC_LIGHTING_EFFECT_DATA {
    uint8  save_effect;
    bool   bSaved;
    int32  MonochromeIndex;      // 1..30  (preset colour selector)
    int32  ManualIndex1..6;      // MANUAL_COLORS_COUNT = 6
    int32  ManualInterval;
    int32  BreathingIndex;
    RGBKB_Color UserDefineColor;
}
```

and `COLOR_CELL { uint32 Index; uint8 R,G,B; uint8 R_Level,G_Level,B_Level; }`
— note the class keeps **both** the raw RGB *and* the separate `*_Level`
fields, which is the smoking gun that the EC only consumes levels.

---

# Addendum — `0x078C` is the missing STICKY ENABLE, and `0x0767` bit map

## `0x078C` (SINGLEKBL_ENABLE) must be `0x01`

Long after the level-range bug was fixed, the keyboard still went dark
after a while and refused to come back.  The cause was `0x078C`.

```
0x078C = 0x02   -> static colour writes are IGNORED, keyboard stays dark
0x078C = 0x01   -> static colour writes take effect       ✓
```

Confirmed by A/B toggling `02 -> 01 -> 02 -> 01` with a red level write
plus trigger each time: only `0x01` produced light.

So the complete static-colour sequence is **four** steps, not three:

```
0x078C <- 0x01        # SINGLEKBL_ENABLE = enable  (STICKY - must be set!)
0x0769 <- level_r     # 1..50
0x076A <- level_g     # 1..50
0x076B <- level_b     # 1..50
0x0767 <- 0x20        # trigger apply (self-clearing)
```

## `0x0767` (TRIGGER_BYTE) bit map, measured

Every bit written individually, one at a time:

| write | read back | meaning |
|---|---|---|
| `0x01` | `0x00` | consumed (transient trigger) |
| `0x02` | `0x00` | consumed — `LightBar_Trigger` |
| `0x04` | `0x00` | consumed (transient) |
| `0x08` | `0x00` | consumed (transient) |
| `0x10` | `0x10` | **sticky** |
| `0x20` | `0x00` | consumed — `RGBKeybaord_Trigger` (the "apply" bit) |
| `0x40` | `0x40` | **sticky** — `RGBLogo_Trigger` |
| `0x80` | `0x80` | **sticky** — `RGBKeybaordWelcome_Trigger` |

Three sticky bits: `0x10`, `0x40`, `0x80`.  The `TriggerByteFlag` enum from
the original reverse-engineering said:

```
LightBar_Trigger            = 0x02
RGBKeybaord_Trigger         = 0x20
RGBLogo_Trigger             = 0x40
RGBKeybaordWelcome_Trigger  = 0x80
```

So `0x40` and `0x80` are the **logo / light-bar** switches — note that
`0x0769/6A/6B` are double-booked as both `RGBKB_LEVEL_*` **and**
`AP_EC_LOGO_*`, so the same level registers drive the A-cover logo when the
logo trigger is enabled.

**Rule: for a static keyboard colour, leave `0x10`, `0x40` and `0x80` all
clear.**  Only pulse `0x20`.

## `0x0768` (STATUS_BYTE) is not a reliable on/off switch

It only accepts `0..3`; writing `4`/`5` is clamped back to `0`/`1`:

```
write 0 -> 0   (Off)
write 1 -> 1   (On)
write 2 -> 2   (Lighting_off)
write 3 -> 3   (Lighting_on)
write 4 -> 0   (Welcome_off  -> clamped)
write 5 -> 1   (Welcome_on   -> clamped)
```

Observed desync: after a successful colour write, `0x0768` sometimes read
`0x00` while the keyboard was clearly lit, and `0x0768 <- 0x00` did **not**
turn the keyboard off.  It mirrors what the EC lighting task thinks its
power state is; it is **not** something the host should drive to turn the
LEDs on or off.  Use `0x078C` for enable and leave `0x0768` alone.

## Do not write 0 to the level registers

`RGB_LEVEL_MIN = 1`.  Writing `0x00` to `0x0769/6A/6B` is rejected — the
read-back keeps the previous value.  To make one channel dark you must write
another channel; there is no per-channel "off" other than turning the whole
keyboard off.

`0x076C/6D/6E` (DEFAULT R/G/B) carry the same 1..50 constraint.  A leftover
invalid value there (we once had `0x076D = 0xFF`) leaves the EC lighting task
in a bad state where subsequent writes have no effect.  **Always write legal
levels into the default registers too.**

## Recovery procedure if the keyboard goes dark

1. `0x078C <- 0x01`
2. `0x076C/6D/6E <- 32 32 32`   (legal defaults)
3. `0x0769/6A/6B <- 32 32 32`
4. `0x0767 <- 0x00`   (clear all sticky bits)
5. `0x0767 <- 0x20`   (trigger)

If it is still dark after that, the EC lighting task itself is wedged and an
EC reset (full power drain) is required.

## Sticky-bit trigger ports discovered on `HIDKeyboard`

```
EC_RGBKBBKL_LEVEL_UPDATE = 0x00F0    write-and-clear
EC_RGBKBBKL_LEVEL_DOWN   = 0x00B1    write-and-clear
EC_RGBKBBKL_LEVEL_UP     = 0x00B2    write-and-clear
EC_SINGLEKBL_LEVEL_CHG   = 0x00B4    write-and-clear
EC_ChinaMode_Change      = 0x00B6
EC_RGBKBBKL_CIRCLE_UP    = 0x00B9
```

All read back `0x00` after a write — they are notification/event ports, not
storage.  `0x00B1/0x00B2` are the kernel's `KEY_KBDILLUMDOWN` /
`KEY_KBDILLUMUP` counterparts.

---

# Addendum — there is NO "off" register; `off` = level 1

After trying and rejecting every plausible switch, the answer turned out to
be the level registers themselves.

## What we tried first (all failed)

| candidate | write | result |
|---|---|---|
| `0x0768` STATUS | `0x00` | no change (it is a state mirror, not a control) |
| `0x078C` SINGLEKBL_ENABLE | `0x00` | no change (it is an *enable*, not a switch) |
| `0x078E` SUPPORTPOWER | `0xE8` | no change |
| `0x00B1` LEVEL_DOWN | `0x01` x5 | no change (pure notification port) |
| `0x0767` | `0x00` | no change (only clears pending triggers) |
| `0x0769/6A/6B` | `0x00` | **rejected by the EC** (below `RGB_LEVEL_MIN`) |

## The answer

```
RGB_LEVEL_MIN = 1
```

Writing **level 1 to all three channels** makes the keyboard dark to the eye.
Writing `0` is rejected — the read-back keeps the old value — which is why
"just write zero" never worked.

So:

```
off  ->  0x0769 = 0x01, 0x076A = 0x01, 0x076B = 0x01, 0x078C = 0x01, 0x0767 = 0x20
on   ->  restore the saved colour levels, same enable + trigger
```

Verified on the machine: `kbdlight off` -> keyboard dark, `kbdlight on` ->
keyboard back to the previous colour.

### Why this is the right model

The EC exposes a **brightness ladder**, not an on/off line.  `RGBKB_Level`
spans `1..50` and `1` is simply the bottom rung — visually indistinguishable
from off.  That also matches the `HIDKeyboard` constants:

```
EC_RGBKBBKL_LEVEL_DOWN = 0x00B1     (KEY_KBDILLUMDOWN)
EC_RGBKBBKL_LEVEL_UP   = 0x00B2     (KEY_KBDILLUMUP)
EC_RGBKBBKL_LEVEL_UPDATE = 0x00F0
```

Those are the kernel's brightness-key notification ports.  A firmware that
models the backlight as a ladder has no separate power bit — it just drives
the rung to its minimum.  `0x0768`/`0x078C` are *policy* state (what the OS
asked for), consumed by the EC lighting task, not electrical switches.

### Consequence for `brightness`

Because `1` is the floor, a `brightness 0` request must map to level `1`,
not `0`.  `to_level(0)` returning `0` is fine on its own (the EC rejects it
and keeps the old value), but the CLI now treats `brightness 0` as "off" and
routes it through the same level-1 path.

## Bonus finding: this machine's PROJECT_ID is not in the enum

```
0x0740 EC_PROJECT_ID_BYTE = 0x19 (25)
```

but `LightingModel.EC_SPEC` only defines:

```
EC_PROJECT_LEGANCY           = 0x00      EC_PROJECT_IDP               = 0x0B
EC_PROJECT_GIxKN             = 0x01      EC_PROJECT_ID6Y              = 0x0C
EC_PROJECT_GJxKN             = 0x02      EC_PROJECT_ID7Y              = 0x0D
EC_PROJECT_GKxCN             = 0x03      EC_PROJECT_PF4MU_PF4MN_PF5MU = 0x0E
EC_PROJECT_GIxCN             = 0x04      EC_PROJECT_CML_Gaming        = 0x0F
EC_PROJECT_GJxCN             = 0x05      EC_PROJECT_GK7NXXR           = 0x10
EC_PROJECT_GK5CN_X           = 0x06      EC_PROJECT_GM5MU1Y           = 0x11
EC_PROJECT_GK7CN_S           = 0x07
EC_PROJECT_GK7CPCS_GK5CQ7Z   = 0x08
```

`0x19` is outside the table (max is `0x11`).  This chassis is a **GM5HG0A**,
and there is a `GM5MU1Y` (`0x11`) but no `GM5HG0A`.  So Control Center falls
through to a legacy/default path on this machine — which explains why its
captured write sequence was so unhelpful (`0x076D <- 0xFF` then trigger, with
no visible effect) and why the direct EC route was the only viable one.

## Final, complete protocol

```
# enable (sticky, required)
0x078C <- 0x01

# keyword-related EC constants, for reference
ADDR_TRIGGER_BYTE       = 0x0767   bit5=0x20 trigger (self-clearing)
                                   bit4=0x10, bit6=0x40, bit7=0x80 sticky
ADDR_STAUTS_BYTE        = 0x0768   0..3, state mirror only
ADDR_RGBKB_LEVEL_R/G/B  = 0x0769/0x076A/0x076B       1..50
ADDR_RGBKB_LEVEL_DEFAULT_R/G/B = 0x076C/0x076D/0x076E 1..50
ADDR_SINGLEKBL_ENABLE   = 0x078C   must be 0x01
ADDR_SINGLEKBL_SUPPORTPOWER = 0x078E

# set a static colour
0x0769 <- level_r       # clamp(round(v/255*50), 1, 50)
0x076A <- level_g
0x076B <- level_b
0x0767 <- 0x20          # apply

# minimum levels = off
0x0769 <- 0x01
0x076A <- 0x01
0x076B <- 0x01
0x0767 <- 0x20
```
