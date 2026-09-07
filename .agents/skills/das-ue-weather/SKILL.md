---
name: das-ue-weather
description: 用户要求设置 Unreal 项目的时间或天气时使用。
user-invocable: false
---

# Unreal 时间与天气

用 `das_ue_weather.exe` 通过 Python 远程执行，设置运行中编辑器场景里 Ultra Dynamic Sky 的时间与 Ultra Dynamic Weather 的天气。程序自己会调同目录的 `das_ue_launcher.exe` 取实例并配好远程执行，不需要先启动编辑器。仅支持 Windows。

程序在 das-ue-import-obj 的包里，按相对路径取，不要另找路径；PowerShell 必须接管道，否则不会等它退出：

```powershell
& "<本 Skill 目录>\..\das-ue-import-obj\ObjUeImport\das_ue_weather.exe" --ue-weather "<项目.uproject>" --time 09:30 | Tee-Object -FilePath "<日志路径>"
& "<本 Skill 目录>\..\das-ue-import-obj\ObjUeImport\das_ue_weather.exe" --ue-weather "<项目.uproject>" --preset "Rain" --save | Tee-Object -FilePath "<日志路径>"
```

- 不要加 `2>&1`，不要用 `Start-Process` 丢掉日志，日志路径放临时目录。缺 `.uproject` 先问用户。
- 一次至少给一项设置，否则报参数错。只下发命令行给了的项，没给的保持原样——「不改」和「设为 0」不一样。
- 时间：`--time HH:MM[:SS]` 与 `--time-of-day 0-2400` 互斥，刻度线性，`09:30` 是 `950`。`Animate Time of Day`、`Randomize Time Of Day`、`Use System Time` 只读不写，开着时日志会提示写入的时间会被覆盖。
- 天气：`--preset <资产>` 会先清掉全部手动覆盖开关；手动项 `--cloud-coverage`、`--rain`、`--snow`、`--fog`、`--dust`、`--wind-strength`、`--lightning` 写值并打开对应覆盖开关；`--wind-direction` 独立，不受预设影响。程序没有查询命令，预设名由用户给。
- 默认只在编辑器里预览，加 `--save` 才保存关卡与 Actor 包。
- 关卡里没有实例时按蓝图新建，放进 `--outliner-folder`（缺省 `DasWeather`）。UDS / UDW 是付费商城资产，工程里找不到蓝图会明确报错，此时用 `--sky-blueprint`、`--weather-blueprint` 指定。
- 退出码 `0` 成功、`1` 执行失败、`2` 参数错误。末行 `UE_WEATHER_RESULT=` 后是单行 JSON，每个任务带 `before` / `after`。
- 报要重启编辑器就让用户重启；同一工程开了多个编辑器实例会报错，要求只留一个。
- 报错时直接报告，不要改为手工操作。
