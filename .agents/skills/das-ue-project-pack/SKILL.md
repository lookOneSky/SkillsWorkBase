---
name: das-ue-project-pack
description: 用户要求打包 UE 工程或打包 DLC 时使用。
user-invocable: false
---

# Unreal 项目打包

在 Windows 上从 Skill 自带配置和 Unreal Engine 目录按工程名自动匹配 `.ulp2`，并用 `RunUAT BuildCookRun` 打包普通版本或 DLC。

1. 获取工程文件夹或 `.uproject`；输出工作目录可以省略。配置仅支持 `debug` 和 `shipping`，未指定时固定使用 `shipping`。DLC 名称可由用户指定；用户未指定时继承匹配 `.ulp2` 的 `DLCName`，两处都没有名称时再询问。
2. 使用 Python 3 运行同级脚本：

   ```powershell
   python "<本 Skill 目录>\pack_ue_project.py" "<工程文件夹>" ["<输出工作目录>"] [--configuration debug|shipping] [--engine-root "<引擎目录>"] [--dlc] [--dlc-name "<DLC 名称>"]
   ```

   用户要求 DLC 打包时追加 `--dlc`；用户提供 DLC 名称时再追加 `--dlc-name`。只预览配置、匹配结果、输出目录和完整命令时追加 `--dry-run`。用户明确要求实际打包时才去掉 `--dry-run`；不要额外执行其他编译或构建命令。
3. 脚本先根据 `.uproject` 或 `--engine-root` 定位 Engine，再查找本 Skill 同级和 Engine 目录中的 `.ulp2` 配置并按工程名匹配；只为最终匹配到的配置打印 `[找到配置文件] <完整路径>`。不搜索工程目录，不要求用户提供配置路径。匹配后继承地图、文化、平台和 UAT 开关，但始终使用本次工程、配置和输出目录。DLC 模式把配置中的 `CreateReleaseVersion` 设为 `false`、`CreateDLC` 设为 `true`，并让 `--dlc-name` 覆盖配置中的 `DLCName`；非 DLC 模式反向设置。`--dry-run` 只预览这些值，实际打包时才写回所选 `.ulp2`。DLC 模式未匹配配置时停止；非 DLC 模式未匹配配置时使用 Win64、Build、Cook、Pak、Compressed、Manifests、Stage、Package 等默认参数。
4. 用户指定输出工作目录时直接使用；未指定时优先读取 `.ulp2` 的 `PackageDir`，其次读取 `BuildCookRun.stagingdirectory`。若配置路径末级是既有的时间输出目录（包括普通、旧式 DLC 或带名称的 DLC 目录），取其父目录作为输出工作目录；配置也没有路径时使用 `<工程目录>\Saved\PackagedBuilds`。普通模式在输出工作目录下新建 `yyyyMMddHHmm`，DLC 模式新建 `yyyyMMddHHmm_DLC_<DLC 名称>`，重名时追加 `_01` 之类的序号。
5. 基线固定放在 `<输出工作目录>\Releases\<yyyyMMddHHmm>\<平台>`，主干与 DLC 必须使用同一个输出工作目录。非 DLC 模式下发 `-createreleaseversionroot` 和 `-createreleaseversion=<本次输出目录名去掉序号后缀>`，并剔除配置继承来的 `dlcname`、`generatepatch`、`stagebasereleasepaks`、`addpatchlevel`。DLC 模式下发 `-basedonreleaseversionroot` 和 `-basedonreleaseversion=<Releases 下最新的可用基线名>`，忽略配置里写死的 `BasedOnReleaseVersionName`；只有含 `<平台>\Metadata\DevelopmentAssetRegistry.bin` 的基线才算可用，找不到时直接报错，提醒先在同一目录完成一次主干打包。
6. 首次 `BuildCookRun` 失败时，仅当日志明确包含 Cook 失败特征才追加 `-skipbuild` 重试一次，让 Cook 重新执行后继续 Stage/Package；不得因 Build、Stage、Package 等其他失败重试，也不得进行第二次 Cook 重试。
7. 报告选中的配置或默认配置、实际 `Shipping`/`DebugGame`、DLC 名称（如有）、输出目录、基线目录、全部日志路径和构建结果。脚本失败时保留并报告原始错误，不猜测修改工程代码。
