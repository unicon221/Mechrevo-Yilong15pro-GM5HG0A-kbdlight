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

## 9. Linux 侧可行方案（不依赖 Windows UI）

方案 A: **Wine + .NET** 跑一个自制 MQTT 客户端发 `Keyboard/Ctrl` → 需要 GCUBridge+GCUService 在 Wine 下跑（未验证）。
方案 B: **直接 EC 写**（已被 UI 协议证实寄存器语义），需破解 effect → EC 字节序列（需 PE 动态抓取）。
方案 C: **PE 侧载完整 Control Center**（本文件所述链路全打包）→ UI 点击 → ecdump watch 抓 EC。

---

## PE Hosting Feasibility (verified on this build)

Analysed `iso-root/sources/boot.wim` (Hiren's BootCD PE, build **22621**, Win11 22H2 kernel):

| Requirement | Present | Notes |
|---|---|---|
| `AppXDeploymentServer.dll` | yes | full AppX stack |
| `AppxPackaging.dll` | yes | |
| `StateRepository*.dll` | yes | |
| `WinTypes.dll`, `Clipc.dll` | yes | WinRT core |
| `AppXSvc` service | yes | `Start=3` (manual), `svchost -k wsappx` |
| `StateRepository` service | yes | `Start=2` (auto), `svchost -k appmodel` |
| `ClipSVC` service | yes | `Start=3` |
| `Appinfo` service | yes | `Start=3` |
| svchost groups `wsappx` / `appmodel` | yes | registered in SOFTWARE hive |
| `Microsoft-Windows-WinPE-AppxPackaging-Package` | installed | official MS optional component |
| `Microsoft-OneCore-AppModel-Activation-Package` | installed | |
| PowerShell + `Add-AppxPackage` | yes | `WindowsPowerShell\v1.0` |
| AppX-blocking ProductPolicy | none found | |
| `AppReadiness` service | **absent** | first-launch preparation; non-fatal |
| `MiniNT` key | present (empty) | WinPE marker |

Conclusion: the PE build officially supports AppX deployment (Microsoft ships the
`WinPE-AppxPackaging` OC). Sideloading `CCU.WinUI` is therefore expected to work.
Fallback if `Add-AppxPackage` fails: loose-folder launch of `CCUWinUI.exe`
(handled automatically by `3-start-controlcenter.bat`).

Note: `Microsoft.UI.Xaml.dll` (WinUI3) is NOT inside the msix, so the
`Microsoft.WindowsAppRuntime.1.7` framework package must be installed first -
both msix files are shipped under `ControlCenter\PreinstallKit\`.

## ISO layout (built)

```
\KbdLightCapture\
  ├─ 0-diagnose.bat               environment report -> diagnose.log
  ├─ 1-install-driver.bat         UWACPIDriver.sys + EC verify
  ├─ 2-capture.bat                live EC watch   -> trace.log
  ├─ 3-start-controlcenter.bat    orchestrator (services + UI + launch)
  ├─ 3a-sideload-uwp.bat          Add-AppxPackage CCU.WinUI
  ├─ ecdump.exe
  ├─ README.txt / README_CN_GBK.txt
  └─ ControlCenter\
       ├─ CCU_WinUI\              656 files (msix unpacked)
       ├─ AiStoneService\         GCUBridge.exe + MyControlCenter\GCUService.exe
       ├─ PreinstallKit\          CCU.WinUI.msix, WindowsAppRuntime 1.7 msix,
       │                          CCU.WinUI.cer, Add-AppDevPackage.ps1
       ├─ ZipFiles\               driver + firmware
       ├─ UserFanTables\
       ├─ CreateShortcut\  DefaultTool\
```

Builder: `pe-build/build-iso.sh` (uses `xorrisofs`, BIOS+UEFI El Torito,
same boot params as the original Hiren ISO).

---

# Wine / Mono reverse-engineering findings (2026-02)

## Why Wine cannot drive the EC

* `GCUBridge.exe` **does** run under Wine-Mono 11.3.0 when its service
  framework is bypassed by a small reflection host
  (`MQTT_SERVER.MQTTServer.Instance()` + `StartMQTTService()`),
  and its MQTT broker really listens on `0.0.0.0:13688`.
* MQTT **credentials** (from `MQTTService.ClientManager::.ctor`):
  ```
  for i in 0..AccountNumber-1:
      ClientId[i] = clientId + "_" + i
      UserName[i] = clientId + "_User_" + i
      Password[i] = clientId + "_Pwd888881772688_" + i
  ```
  managers: `_UWPClient = ClientManager("UWPClient", 20)`,
  `_KeyboardClient = ClientManager("MyKeyboard", 20)`,
  `_MyTrayClient`, `_PluginClient`.
* `GCUService.exe` (the process that actually writes the EC) is protected by
  **ConfuserEx anti-tamper**. Its `<Module>:.cctor` decrypts method bodies at
  runtime. Under Wine-Mono this fails:
  ```
  TypeInitializationException: Invalid IL code in <Module>:.cctor ();
      IL_000a: stloc.0
  ```
  → ConfuserEx emits a Windows-only JIT-compatible module initializer.
  **Therefore GCUService can never execute under Mono/Wine.**

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

The only remaining viable capture path is the **WinPE ISO** (real
Windows JIT → ConfuserEx decrypts correctly).  The API/struct knowledge above
makes the capture much easier to interpret and allows a **minimal .NET
reflection host** to be used inside PE instead of sideloading the whole
WinUI app:

```csharp
var lm = Activator.CreateInstance(asm.GetType("LightingModel.LM_Manager"));
lm.GetType().GetMethod("LM_Init").Invoke(lm, new object[]{null});
lm.GetType().GetMethod("LM_SetEffectALL").Invoke(lm, new object[]{
    /*mode*/1, /*effect*/0, /*light*/100, /*speed*/0, /*dir*/-1,
    /*color*/rgbColorStruct, /*save*/1, /*bg*/0, /*alpha*/null });
```

---

# Addendum — PE kit v3: read-only ISO fix + direct EC path

## Why the first PE run failed

Every line printed `Access is denied.` because **`Y:\` (the ISO) is
mounted read-only in WinPE**.  All the scripts were writing their logs
next to themselves:

```
set "CAPDIR=%~dp0"
"..\ecdump.exe" dump 0700 0780 > "%CAPDIR%\before.txt"   <-- ACCESS DENIED
```

The scripts themselves ran fine; only the redirections failed.

### Fix
`_common.bat` now defines two separate roots:

| variable | meaning | writable |
|----------|---------|----------|
| `SRC` (`%SRC%`)  | where the kit was launched from (the ISO, `Y:\KbdLightCapture`) | no |
| `WORK` (`%WORK%`) | RAM disk, `X:\KbdLightCapture` (falls back to `T:`, then `%TEMP%`) | yes |

Every log / dump / staged copy goes to `WORK`.  `0-diagnose.bat`
deliberately probes `SRC` for writability and reports the result
instead of assuming.

## `Appx` module load failure (side-load path)

```
The 'Add-AppxPackage' command was found in the module 'Appx',
but the module could not be loaded.
```

Root cause: `Appx.psd1` declares

```
ModuleToProcess = 'Microsoft.Windows.Appx.PackageManager.Commands'
FormatsToProcess = 'Appx.format.ps1xml'
```

`Microsoft.Windows.Appx.PackageManager.Commands.dll` references the
WinRT metadata assembly **`Windows`**, which is resolved from
`%SystemRoot%\System32\**WinMetadata\**windows.*.winmd`.

**WinPE does not ship `System32\WinMetadata\` at all** (verified by
listing the `boot.wim`), so the assembly cannot be resolved and the
module fails to load.  The PE does contain `AppXDeploymentServer.dll`,
`AppxPackaging.dll`, `StateRepository*`, and servicing
`Microsoft-OneCore-APPXDeployment-*` packages, so it *looks* capable —
but the WinRT projection metadata is missing.

Consequence: the side-load path is fragile.  It is kept only as a
fallback; the primary path no longer needs AppX.

## The direct EC path (primary)

`AcpiCtrl` and `MyEcCtrl` are fully hollowed by ConfuserEx — every
method body is `ldstr "Runtime exception"` + `throw`.  Only the
**P/Invoke declarations survive**, because those are metadata:

```csharp
pinvokeimpl("kernel32.dll")    CreateFile / DeviceIoControl / CloseHandle
pinvokeimpl("ACPIDriverDll.dll") SMAPCTable
```

That is enough to build an equivalent client from scratch.  `KbdHost.exe`
now has stand-alone `ec-*` commands that never touch the packed code:

```
KbdHost.exe ec-info                 read 0x0760,0x0765..0x076B
KbdHost.exe ec-dump 0700 0780       dump a register range
KbdHost.exe ec-set 0769 64          write one byte
KbdHost.exe ec-static FF0000 [lv]   write a static single colour
```

Device access:

```csharp
h = CreateFile("\\.\ACPIDriver", GENERIC_READ|GENERIC_WRITE,
               FILE_SHARE_READ|FILE_SHARE_WRITE, 0, OPEN_EXISTING, 0, 0);
// buffer = { uint32 addr; uint32 data; }   (8 bytes, little endian)
DeviceIoControl(h, 0x9C40A488, buf, 8, out, 8, out n, 0);   // EC read
DeviceIoControl(h, 0x9C40A48C, buf, 8, out, 8, out n, 0);   // EC write
```

`ec-static` writes, in order:

```
0x0760 <- 0x0F     mode
0x0769 <- level    RGB level R
0x076A <- level    RGB level G
0x076B <- level    RGB level B
0x076C <- r        RGB default R
0x076D <- g        RGB default G
0x076E <- b        RGB default B
0x0767 <- 0x20     RGBKeybaord_Trigger   (self-clearing)
```

then reads the registers back.

## The driver

`ControlCenter\ZipFiles\UWACPIDriver.zip` contains a
signed **KMDF 1.15 kernel driver**.  From `UWACPIDriver.inf`:

```
[Standard.NTamd64]
%UWACPIDriver.DeviceDesc%=UWACPIDriver_Device, ACPI\INOU0000

[UWACPIDriver_Service_Inst]
ServiceType    = 1     ; SERVICE_KERNEL_DRIVER
StartType      = 3     ; SERVICE_DEMAND_START
ServiceBinary  = %12%\UWACPIDriver.sys
```

`UWACPIDriver.DeviceDesc = "ACPIDriver"` — i.e. the Win32 device name
`\\.\ACPIDriver`.

The HWID `ACPI\INOU0000` is exactly this machine's DSDT node:

```asl
Device (INOU)
{
    Name (_HID, "INOU0000")
    Name (_UID, Zero)
    ...
    Name (_CRS, ResourceTemplate () {
        Memory32Fixed (ReadWrite, 0xFED50000, 0x00001000)
    })
    ...
}
```

WinPE 22621 already ships `Wdf01000.sys` / `WdfLdr.sys` (KMDF is
backward compatible), so the driver installs and binds normally.
`1-install-driver.bat` tries, in order:

1. `drvload <inf>`      (WinPE-native, binds to the live device)
2. `pnputil /add-driver <inf> /install`
3. `pnputil /scan-devices`
4. `sc create UWACPIDriver type= kernel start= demand` + copy the `.sys`

## Pre-unpacked costura payload

`GCUService.exe` embeds ~40 dependencies as `costura.<name>.dll.compressed`
(raw deflate, no zlib header).  They are now **decompressed at ISO build
time on Linux** so they sit next to `GCUService.exe` as plain DLLs:

```python
zlib.decompress(open(f,'rb').read(), -15)
```

36 files, including `naudio.dll`, `librehardwaremonitorlib.dll`,
`newtonsoft.json.dll`, `hidsharp.dll`, `m2mqtt.net.dll`,
`system.management.automation.dll`.

## Driver register map (repeated for convenience)

```
0x0760  mode                 default 0x0F
0x0765  SUPPORT_BYTE1        0xA1
0x0766  SUPPORT_BYTE2        bit2 = RGB  (seen 0x94)
0x0767  TRIGGER_BYTE         SELF-CLEARING
          0x02 light bar / 0x20 RGB keyboard / 0x40 RGB logo
          0x80 RGB keyboard welcome
0x0768  STATUS_BYTE          0..5
0x0769  RGB level R          0x00,0x28,0x3C,0x50,0x64,0x78,0x8C,0xA0,0xB4,0xC8
0x076A  RGB level G
0x076B  RGB level B
0x076C  RGB default R
0x076D  RGB default G
0x076E  RGB default B
0x076F  MUSIC_NO
0x078C  SINGLEKBL / EC_LOGO_CONFIRM
0x0D00  AP_OEM_SingleZone    = 0x05
0x0D02  RGB copy             = 0x32
0x0D03  RGB copy             = 0x32

NEVER WRITE (fan control):
  0x0751 0x0741 0x078C 0x078E 0x0748
  (0x0751 = 0x40 once caused maximum fan speed)
```

---

# Addendum — Chinese (mojibake) fix in WinPE

## Symptom

Every Chinese character in the PE printed as garbage / boxes.

## Investigation

Three things were checked in `boot.wim`:

1. **NLS code page** — `HKLM\SYSTEM\...`/`SOFTWARE\Microsoft\Windows NT\
   CurrentVersion\NLS\CodePage`:

   ```
   ACP    = 936
   OEMCP  = 936
   MACCP  = 10008
   ```

   Already Simplified Chinese. **Not the problem.**

2. **Font files + GDI registration** — `Windows\Fonts` contains the CJK fonts
   and `...\CurrentVersion\Fonts` registers them:

   ```
   'simsun & nsimsun (truetype)'      -> simsun.ttf
   'noto sans cjk sc (truetype)'      -> notosanscjk-regular.ttc
   'noto sans cjk sc bold (truetype)' -> notosanscjk-bold.ttc
   ```
   plus `FontSubstitutes`: `Microsoft YaHei -> SimSun`.

   **Not the problem either.**

3. **The real cause — two independent bugs, both mine:**

   **a) `chcp 437`**

   The scripts forced the console onto the US code page:

   ```bat
   chcp 437 >nul 2>&1
   ```

   This overrode the system's native 936.  Any byte >0x7F was then
   reinterpreted as CP437 box-drawing characters.

   **b) The console font list has no CJK face**

   The Windows console does **not** use the GDI font table.  It uses a
   separate list:

   ```
   HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Console\TrueTypeFont
        "0"  = "Lucida Console"
        "00" = "Consolas"
   ```

   Neither `Lucida Console` nor `Consolas` has CJK glyphs.  So even with
   code page 936 the console had no way to *draw* a Chinese character.

   The per-user face comes from `DEFAULT\Console\FaceName`, which was
   `__DefaultTTFont__` — i.e. "resolve slot `0`" → `Lucida Console`.

## Fix

### WIM hives  (`patch-hive-fonts.py`, run by `build-iso.sh` stage 0)

`SOFTWARE` — extend the console font list:

```
"0"      = "Lucida Console"
"00"     = "Consolas"
"000"    = "SimSun"             <- added
"0000"   = "NSimSun"            <- added
"00000"  = "Noto Sans CJK SC"   <- added
"000000" = "Microsoft YaHei"    <- added
```

`DEFAULT` — make SimSun the default face:

```
FaceName         = "SimSun"     (was "__DefaultTTFont__")
FontFamily       = 0
FontWeight       = 400
FontSize         = 18
ScreenBufferSize = (120 << 16) | 5000
WindowSize       = (120 << 16) | 40
```

Note: python-hivex has no `value_set_value`; only `node_set_value`.
`node_set_value` **replaces** an existing value with the same key, so it
works as an upsert.

Re-injection uses `wimlib-imagex update` reading commands from **stdin**
(`--command` may only be given once):

```sh
printf 'add %s /Windows/System32/config/SOFTWARE\nadd %s /Windows/System32/config/DEFAULT\n' \
    "$TMP/SOFTWARE" "$TMP/DEFAULT" | wimlib-imagex update "$WIM" 1
```

### Scripts

* every `.bat` now does `chcp 936`
* `_common.bat` also re-applies the font registry at run time (once per
  boot, guarded by a flag file in `%TEMP%`) because registry edits do not
  always survive a WinPE boot:

```bat
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Console\TrueTypeFont" ^
        /v 000 /t REG_SZ /d SimSun /f
reg add "HKCU\Console" /v FaceName   /t REG_SZ    /d SimSun /f
reg add "HKCU\Console" /v FontFamily /t REG_DWORD /d 0      /f
```

* `README_CN_GBK.txt` is GBK-encoded to match code page 936.

## Verification

Extracted `SOFTWARE` from the `boot.wim` **inside the finished ISO** and
confirmed the six-entry font list and `NLS\CodePage\ACP = 936`.

Everything else in the kit is unchanged and byte-identical.

---

# Addendum — PE run #2 analysis (`tee` missing, driver OK)

## What the logs proved

`log/driver.log` and `log/diagnose.log` from the second PE boot:

### Driver: WORKS

```
--- drvload ---
DrvLoad: Unable to load ...\UWACPIDriver.inf (Error 0x80070103).
  drvload exit=3

--- pnputil add-driver ---
Adding driver package:  UWACPIDriver.inf
Driver package added successfully. (Already exists in the system)
Published Name:         oem325.inf
Driver package is up-to-date on device: ACPI\INOU0000\0

--- service check ---
SERVICE_NAME: UWACPIDriver
        TYPE               : 1  KERNEL_DRIVER
        STATE              : 4  RUNNING
```

* `0x80070103` = `ERROR_NO_MORE_ITEMS` — drvload's way of saying "already
  bound", **not** a failure.
* `ACPI\INOU0000\0` means PnP matched the ACPI node from the DSDT.
* Service `UWACPIDriver` is **RUNNING**.

### EC access: WORKS

```
0x0766 = 0x94
0x0765 = 0xA1
```

Read through `\\.\ACPIDriver` with `ecdump.exe read 0766`.  So the whole
EC path is functional.

### The actual failure: no `tee.exe`

```
[3/4] Reading current EC registers ...
'tee' is not recognized as an internal or external command,
operable program or batch file.
```

`3-start-controlcenter.bat` piped KbdHost output through `| tee <file>`.
WinPE has no `tee`.  Every one of the six `tee` invocations aborted, so
the script died at the first one and the prompt for a colour was never
reached.  KbdHost itself was fine.

Also `0-diagnose.bat` used `where powershell` — WinPE has no `where.exe`
either.

## Fixes

### `tee` replacement

WinPE has no tee, so the `:run` helper appends to a log and then echoes
the log to the console:

```bat
:run
set "RUNLOG=%~1"
set "RUNCMD="
shift
:run_collect
if "%~1"=="" goto run_go
set "RUNCMD=!RUNCMD! %~1"     REM no parentheses: %1 must re-parse
shift
goto run_collect
:run_go
if defined RUNCMD set "RUNCMD=!RUNCMD:~1!"
echo --- %DATE% %TIME% : !RUNCMD! --- >> "%RUNLOG%" 2>&1
!RUNCMD! >> "%RUNLOG%" 2>&1
set "RC=!errorlevel!"
echo --- exit=!RC! --- >> "%RUNLOG%" 2>&1
type "%RUNLOG%"
exit /b 0
```

Two cmd traps handled here:

* `%*` does **not** re-expand after `shift`, so the arguments are
  collected one by one.
* `%1` inside a parenthesised block is expanded when the **whole block**
  is parsed, so the accumulation must not use `( ... )`.

### `where` replacement

```bat
if exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" (
    echo [OK] powershell.exe
) else (
    echo [MISS] powershell.exe
)
```

### `errorlevel` inside blocks

`1-install-driver.bat` had

```bat
if errorlevel 1 ( echo ... ) else ( echo ... )
```

inside an outer parenthesised block.  `errorlevel` is expanded at parse
time of the enclosing block, so it read a stale value.  Rewritten with
`goto` labels and the `&&` / `set` idiom:

```bat
set "HAVESVC=0"
sc query UWACPIDriver 2>nul | findstr /i /c:"SERVICE_NAME: UWACPIDriver" >nul 2>&1 && set "HAVESVC=1"
if "%HAVESVC%"=="0" goto :drv_manual
```

### `EcRead` ABI bug

The old heuristic

```csharp
data = (d1 != 0) ? d1 : (d4 != 0 ? d4 : (di != 0 ? di : (uint)ret));
```

returned **0 for a legitimate zero register**, and could pick the wrong
field.  The Uniwill driver copies the whole `{addr,data}` struct to the
output buffer, so the value is at offset 4:

```csharp
uint d4 = BitConverter.ToUInt32(outb, 4);
uint d1 = BitConverter.ToUInt32(outb, 0);
uint di = BitConverter.ToUInt32(inb, 4);
if (d4 != 0 || d1 == addr) data = d4;      // normal path
else if (di != 0)          data = di;
else if (d1 != 0)          data = d1;
else                       data = 0;       // genuine zero
```

A new `ec-raw <addr>` command dumps the whole 8-byte round-trip so the
ABI can be confirmed on the real machine:

```
[ec] addr=0766 ok=True ret=8
[ec] out: 66-07-00-00-94-00-00-00
[ec] decoded = 94
```

### `1-install-driver.bat` return code

Now exits **1** when the EC is not readable, and 0 when it is, so
`3-start-controlcenter.bat` can report honestly:

```bat
call "%SRC%\1-install-driver.bat" /auto
set "DREXIT=!errorlevel!"
if "!DREXIT!"=="0" ( echo   [OK] driver installed and EC readable
) else ( echo   [WARN] EC not verified by the driver step ) 
```

### `ec-static` widened

`ec-info` / `ec-static` now show the full relevant window:

```
0x0760 0x0765 0x0766 0x0767 0x0768
0x0769 0x076A 0x076B 0x076C 0x076D 0x076E
0x076F 0x0748 0x078C 0x0D00 0x0D02 0x0D03
```

before and after a 300 ms settle delay, so the diff shows exactly which
registers the write touched.

## Environment facts learned

| item | value |
|---|---|
| PE build | 22621.2428, Microsoft Windows 11 Enterprise |
| drives | `C: D: E: X: Y:` (X: = RAM disk, 4.2 GB free) |
| AppXSvc | RUNNING |
| StateRepository | RUNNING |
| Appinfo | RUNNING |
| ClipSVC | STOPPED (exit 1077) |
| AppReadiness | **does not exist** |
| `Import-Module Appx` | FAIL — `Could not find Windows Runtime type 'Windows.Management.Deployment.StubPackageOption'` |
| .NET | Framework64 v4.0.30319 present |
| working path | `X:\KbdLightCapture` writable, source `Y:\KbdLightCapture` read-only (correct) |

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
level = clamp(round(v / 255.0 * 50.0), 0, 50)   # 0 stays 0 (= fully dark)
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

The `trace.log` from the WinPE run showed them oscillating between
`0x3C` and `0x47` roughly every 300 ms for the whole 124 s capture.  That
was **the fans tracking temperature**, not a keyboard animation.  Don't be
misled again.

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

## `0x0768` (STATUS_BYTE) is a *status* register, not a switch

It accepts `0..3` and keeps the value (it is a writable register, not a
clamp), but writing it does **not** change the LED output:

```
write 0 -> 0   (Off)           LED unchanged
write 1 -> 1   (On)            LED unchanged
write 2 -> 2   (Lighting_off)  LED unchanged  <- tested for 30s, no effect
write 3 -> 3   (Lighting_on)   LED unchanged
write 4 -> 0   (Welcome_off  -> clamped)
write 5 -> 1   (Welcome_on   -> clamped)
```

It mirrors what the EC lighting task thinks its power state is, i.e. it is a
*desired-state* store that a vendor-side consumer would act upon.  The
consumer (`ILM_RGBKB_SetPower`) is ConfuserEx-stubbed in GCUService, and the
EC firmware itself never acts on `0x0768` alone.  **Leave it alone.**

## ★★ `0x0769/6A/6B = 0` DOES turn the LEDs fully off — the real gotcha

**Corrected 2026-10-16.**  Earlier revisions of this document claimed that
`0x00` was rejected by the EC and that `off` could only mean "level 1".
Both claims were wrong.  What actually happens:

> The EC has a periodic task that copies the **current levels**
> (`0x0769/6A/6B`) from the **default levels** (`0x076C/6D/6E`).

So:

| what you write | what you see |
|---|---|
| `0x0769/6A/6B <- 0/0/0` only | goes dark for ~1 s, then **snaps back** to the default levels |
| `0x0769/6A/6B <- 0/0/0` **and** `0x076C/6D/6E <- 0/0/0`, then `0x0767 <- 0x20` | **stays fully dark** (verified >30 s) |
| write 0 but **omit** `0x0767 <- 0x20` | no change at all (trigger is required) |

The "read-back keeps the previous value" observation that started this myth
was just the resync: reading 1 s after the write shows the restored default.

`0` and `1` are genuinely different:

```
level 0  ->  LED fully off, no glow
level 1  ->  dimmest step, still clearly visible in a dark room
```

Working sequence (this is what `kbdlight.off()` does):

```
0x078C <- 0x01                 # enable static colour
0x0769 <- 0x00                 # current R
0x076A <- 0x00                 # current G
0x076B <- 0x00                 # current B
0x076C <- 0x00                 # DEFAULT R   <- must match, or it snaps back
0x076D <- 0x00                 # DEFAULT G
0x076E <- 0x00                 # DEFAULT B
0x0767 <- 0x20                 # trigger, write-and-clear
```

`0x076C/6D/6E` still must never hold an *invalid* value (`> 50`, e.g. the
`0xFF` once left there by the vendor tool) — that wedges the EC lighting
task.  Valid means `0..50`, and `0` is now known to be legal and meaningful.

## Recovery procedure if the keyboard goes dark

1. `0x078C <- 0x01`
2. `0x076C/6D/6E <- 32 32 32`   (legal defaults, doubles as "restore colour")
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

# Addendum — `off` = level **0**, and you must write the DEFAULT levels too

**Corrected 2026-10-16 (supersedes the earlier "there is NO off, use level 1"
addendum).**

After rejecting every plausible switch first, the answer turned out to live in
the level registers after all — but with a hidden coupling that made naive
tests fail.

## The trap: `0x076C/6D/6E` is the master

> **The EC runs a periodic task that copies the current levels
> (`0x0769/6A/6B`) from the default levels (`0x076C/6D/6E`).**

That is the whole story.  Every confusing observation we had is a consequence:

| write | read-back right after | ~1 s later | LED |
|---|---|---|---|
| current `<- 0/0/0` only | `0x00 0x00 0x00` | `0x32 0x19 0x00` (the defaults!) | dark for a second, then back on |
| current + default `<- 0/0/0` | `0x00 0x00 0x00` | `0x00 0x00 0x00` | **stays dark** |
| current `<- 0/0/0`, no trigger | unchanged | unchanged | nothing |

So the old note "writing `0x00` is rejected, the read-back keeps the previous
value" was a misread of the resync: we were reading ~1 s after the write and
measuring the *restored default*, not a rejection.

Likewise "we saw it go dark once and never reproduced it" — the one success
happened while the default registers happened to still be `0/0/0` from an
earlier experiment.

## What we tried (all genuinely ineffective)

| candidate | write | result |
|---|---|---|
| `0x0768` STATUS | `0/1/2/3`, held 30 s each | LED never changed (state mirror, not a switch) |
| `0x078C` SINGLEKBL_ENABLE | `0x00` | no change (it is an *enable*, not a switch) |
| `0x078E` SUPPORTPOWER | `0xE8` | no change (read-only capability bits) |
| `0x00B1` LEVEL_DOWN | `0x01` x5 | no change (pure notification port) |
| `0x0767` | `0x00` | no change (only clears pending triggers) |
| `0x0782` Light_SetToChinaMode | `0x00` / `0x01` | no change (BIOS OEM byte) |
| `0x0D02/0D03` | `0x00` | no change |

A full EC diff (0x700-0x7FF, 0xD00-0xD5F, 0xF00-0xFFF, 608 registers) between
"static colour" and "welcome animation" showed exactly **one** meaningful
byte: `0x0767` (`0x00` vs `0x80`).  There is no effect-number register.

## The answer

```
level 0  ->  LED fully off,   no glow at all
level 1  ->  dimmest step,    still clearly visible in a dark room
level 50 ->  max brightness
```

The working sequence (exactly what `kbdlight.off()` does):

```
0x078C <- 0x01     # enable static colour
0x0769 <- 0x00     # current R
0x076A <- 0x00     # current G
0x076B <- 0x00     # current B
0x076C <- 0x00     # DEFAULT R   <- without these the EC snaps back
0x076D <- 0x00     # DEFAULT G
0x076E <- 0x00     # DEFAULT B
0x0767 <- 0x20     # trigger (write-and-clear, reads back 0)
```

Verified on the machine: stays fully dark for 30+ s (before the fix it went
dark for ~1 s and snapped back).  `kbdlight on` restores the saved colour.

### Consequence for `brightness`

`to_level(0)` returns `0`, which is now a legal and meaningful value.  The
CLI routes `brightness 0` straight to `off()`.

## Model summary

The EC exposes a **brightness ladder `0..50`** where `0` really is zero — but
it also mirrors the ladder into two identical register pairs, and the default
pair wins on a timer.  Keep both in sync and everything behaves:

```python
def set_levels(r, g, b):
    write(0x0769, r); write(0x076A, g); write(0x076B, b)   # current
    write(0x076C, r); write(0x076D, g); write(0x076E, b)   # default (must match)
    write(0x078C, 0x01)                                     # enable
    write(0x0767, 0x20)                                     # trigger
```

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
ADDR_RGBKB_LEVEL_R/G/B  = 0x0769/0x076A/0x076B       0..50  (0 = dark)
ADDR_RGBKB_LEVEL_DEFAULT_R/G/B = 0x076C/0x076D/0x076E 0..50 (mirror; EC resyncs)
ADDR_SINGLEKBL_ENABLE   = 0x078C   must be 0x01
ADDR_SINGLEKBL_SUPPORTPOWER = 0x078E

# current levels (0..50; 0 = channel off / fully dark)
0x0769 <- level_r       # clamp(round(v/255*50), 1, 50) for lit colours
0x076A <- level_g
0x076B <- level_b
# DEFAULT levels -- MUST mirror the current ones or the EC will resync
0x076C <- level_r
0x076D <- level_g
0x076E <- level_b
0x0767 <- 0x20          # apply

# full off
0x0769 <- 0x00
0x076A <- 0x00
0x076B <- 0x00
0x076C <- 0x00
0x076D <- 0x00
0x076E <- 0x00
0x0767 <- 0x20
```
