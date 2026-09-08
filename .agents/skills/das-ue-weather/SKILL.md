---
name: das-ue-weather
description: 用户要求设置 Unreal 项目的时间或天气时使用。
user-invocable: false
---

# Unreal 时间与天气

Ultra Dynamic Sky 管时间，Ultra Dynamic Weather 管天气。`das_ue_weather.exe` 通过 Python 远程执行把设置写进运行中的编辑器场景；取编辑器实例、配远程执行、关卡里没实例时新建，全由它自己完成，不用先做别的准备。仅支持 Windows。

程序在 das-ue-import-obj 的包里，按相对路径取；PowerShell 必须接管道，否则不会等它退出：

```powershell
& "<本 Skill 目录>\..\das-ue-import-obj\ObjUeImport\das_ue_weather.exe" --ue-weather "<项目.uproject>" --time 09:30 | Tee-Object -FilePath "<日志路径>"
& "<本 Skill 目录>\..\das-ue-import-obj\ObjUeImport\das_ue_weather.exe" --ue-weather "<项目.uproject>" --preset "Rain" | Tee-Object -FilePath "<日志路径>"
```

- 缺 `.uproject` 先问用户；一次至少给一项设置，否则报参数错。
- 只下发命令行给了的项，没给的保持原样——「不改」和「设为 0」不一样。
- 时间：`--time HH:MM[:SS]` 与 `--time-of-day 0-2400` 互斥，刻度线性，`09:30` 是 `950`。
- 天气只支持 `--preset <资产名或路径>`；不要使用云量、雨雪、雾、沙尘、风或闪电等数值参数。设置预设会清除手动天气覆盖。
- 标准预设：`Clear_Skies`、`Partly_Cloudy`、`Cloudy`、`Overcast`、`Foggy`、`Rain_Light`、`Rain`、`Rain_Thunderstorm`、`Snow_Light`、`Snow`、`Snow_Blizzard`、`Sand_Dust_Calm`、`Sand_Dust_Storm`；也可使用用户给的自定义预设资产名或路径。
- 默认只在编辑器里预览。除非用户明确要求保存关卡或保存修改，否则绝不加 `--save`；“设置”“修改”“应用”时间或天气本身不表示要保存。
- 退出码 `0` 成功、`1` 执行失败、`2` 参数错误；末行 `UE_WEATHER_RESULT=` 是单行 JSON，每个任务带 `before` / `after`，按它报告结果。
