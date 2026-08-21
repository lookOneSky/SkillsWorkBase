---
name: das-ue-project-pack
description: 在 Windows 上从 Skill 自带配置和 Unreal Engine 目录按工程名自动匹配 .ulp2，并用 RunUAT BuildCookRun 打包项目；用户要求打包 UE 项目文件夹、复用 Launcher Profile 或在无配置时按默认参数打包时使用。
user-invocable: false
---

# Unreal 项目打包

1. 获取工程文件夹或 `.uproject`；配置仅支持 `debug` 和 `shipping`，未指定时固定使用 `shipping`。`debug` 映射为 UE 的 `DebugGame`。
2. 使用 Python 3 运行同级脚本：

   ```powershell
   python "<本 Skill 目录>\pack_ue_project.py" "<工程文件夹>" ["<输出工作目录>"] [--configuration debug|shipping] [--engine-root "<引擎目录>"]
   ```

   只预览配置、匹配结果、输出目录和完整命令时追加 `--dry-run`。用户明确要求实际打包时才去掉 `--dry-run`；不要额外执行其他编译或构建命令。
3. 脚本先根据 `.uproject` 或 `--engine-root` 定位 Engine，再查找本 Skill 同级和 Engine 目录中的 `.ulp2` 配置；每找到一个候选文件都打印 `[找到配置文件] <完整路径>`，随后按工程名匹配。不搜索工程目录，不要求用户提供配置路径。匹配后继承地图、文化、平台和 UAT 开关，但始终使用本次工程、配置和输出目录。未匹配配置时使用 Win64、Build、Cook、Pak、Compressed、Manifests、Stage、Package 等默认参数。
4. 输出工作目录未指定时，优先取配置的 `PackageDir` 或 `scripts[].stagingdirectory`：若末级是 `yyyyMMddHHmm` 时间目录，则使用其父目录；没有配置时使用 `<工程>/Saved/PackagedBuilds`。默认在工作目录下新建本次 `yyyyMMddHHmm` 目录；仅在用户要求精确目录时传 `--exact-output`。
5. 首次 `BuildCookRun` 失败时，仅当日志明确包含 Cook 失败特征才追加 `-skipbuild` 重试一次，让 Cook 重新执行后继续 Stage/Package；不得因 Build、Stage、Package 等其他失败重试，也不得进行第二次 Cook 重试。
6. 报告选中的配置或默认配置、实际 `Shipping`/`DebugGame`、输出目录、全部日志路径和构建结果。脚本失败时保留并报告原始错误，不猜测修改工程代码。
