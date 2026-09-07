---
name: das-ue-weather
description: 用户要求设置 Unreal 项目的时间或天气时使用。
user-invocable: false
---

# Unreal 时间与天气

通过 Python 远程执行，操作运行中编辑器场景里的 Ultra Dynamic Sky（时间）与 Ultra Dynamic Weather（天气）。仅支持 Windows。

## 调用顺序

1. 运行 das-ue-autoconfig 的 `configure_ue_python.py` 开启 Python 远程执行；同一会话内已成功配置过就跳过。
2. 运行 das-ue-launch 的 `launch_ue_editor.py "<项目>" --json "<临时目录>\ue_launch.json"`。
3. 把第 2 步写出的实例 JSON 路径传给本 Skill 的脚本：

```powershell
python "<本 Skill 目录>\ue_time.py" --launch-result "<实例JSON>" get
python "<本 Skill 目录>\ue_time.py" --launch-result "<实例JSON>" set --time "09:30"
python "<本 Skill 目录>\ue_time.py" --launch-result "<实例JSON>" set --time-of-day 950 --save

python "<本 Skill 目录>\ue_weather.py" --launch-result "<实例JSON>" get
python "<本 Skill 目录>\ue_weather.py" --launch-result "<实例JSON>" list-presets
python "<本 Skill 目录>\ue_weather.py" --launch-result "<实例JSON>" set --preset "Rain"
python "<本 Skill 目录>\ue_weather.py" --launch-result "<实例JSON>" set --rain 5 --fog 2 --save
```

- `--launch-result` 也接受行内 JSON。省略它时用 `--project "<项目>"`，脚本自行推导。
- 报 `[错误] 未发现运行中的编辑器` 就回到第 2 步；报 `[错误] Python 远程执行未开启` 就回到第 1 步并重启编辑器。脚本不会替用户改配置或启动编辑器。
- `.uproject` 的 `EngineAssociation` 定位不到引擎时（自编译引擎未注册到 `HKCU\SOFTWARE\Epic Games\Unreal Engine\Builds` 就会这样），给启动器和本 Skill 的脚本都加 `--engine-root "<引擎根目录>"`。

## 时间

- `--time` 用 `HH:MM[:SS]`，`--time-of-day` 用 UDS 原始 0-2400 刻度，两者互斥。刻度是线性的，`09:30` 对应 `950`。
- 只改初始时刻，不动 `Animate Time of Day`、`Randomize Time Of Day`、`Use System Time`；其中任一开启时输出 `[提示]`，说明运行时可能覆盖本次设置。

## 天气

- `--preset` 接受唯一资产名或完整对象路径，先用 `list-presets` 确认可选值。
- 手动参数 `--cloud-coverage`、`--rain`、`--snow`、`--fog`、`--dust`、`--wind-strength`、`--lightning` 写手动天气状态值，并打开对应的逐值覆盖开关（`Lightning` 没有覆盖开关，只在未选预设时生效）。
- 只给手动参数时不动预设，其余天气状态保留；给了 `--preset` 时先清除旧覆盖开关，再写预设，最后应用同次命令里的手动参数。
- `--wind-direction` 单独写 `Base Wind Direction`，不修改天气预设资产。

## 通用

- 实例按蓝图类及继承关系识别，不依赖 Actor 标签；缺实例时用 AssetRegistry 按类查蓝图，不写死路径。候选不唯一时报错并列出对象路径，用 `--sky-actor`、`--weather-actor`、`--sky-blueprint`、`--weather-blueprint` 指定。
- 设置命令会补齐缺少的实例，在当前编辑关卡原点创建并放入 `DasWeather` 大纲文件夹；已有实例保留位置与其他配置，只写请求涉及的属性。读取命令不创建实例。
- 默认只在编辑器预览，加 `--save` 才保存；写入包在编辑器事务里，支持撤销。
- 末行 `UE_TIME_RESULT=` / `UE_WEATHER_RESULT=` 后是单行 JSON，含实例对象路径、是否新建、`before`/`after` 数值与保存状态。
- 脚本报错时直接报告，不要改为手工操作。
