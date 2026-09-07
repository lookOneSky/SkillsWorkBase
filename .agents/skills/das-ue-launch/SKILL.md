---
name: das-ue-launch
description: 用户要求启动、打开 Unreal 编辑器，或其他任务需要正在运行的编辑器实例时使用。
user-invocable: false
---

# Unreal 启动编辑器

拿到指定 `.uproject` 正在运行的 Unreal 编辑器，没有就启动一个，并开启 Python 远程执行。仅支持 Windows。

程序在 das-ue-import-obj 的包里，按相对路径取，不要另找；PowerShell 必须接管道，否则不会等它退出：

```powershell
& "<本 Skill 目录>\..\das-ue-import-obj\ObjUeImport\das_ue_launcher.exe" --ue-launch "<项目.uproject>" | Tee-Object -FilePath "<日志路径>"
```

- 缺 `.uproject` 先问用户，不要猜。`das_ue_weather.exe` 会自己调它，那类任务不用先跑本 Skill。
- 结果看末行 `UE_LAUNCH_RESULT=` 的 JSON；`restart_required` 为 `true` 就让用户重启编辑器，不要自己关。
- 报错直接报告，不要改为手工启动或手工改配置。
