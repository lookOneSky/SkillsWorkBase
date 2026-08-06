---
name: das-ue-plugin-pack
description: 在 Windows 上按 Skill 固定清单把 DasUnreal、cesium-unreal、DasApplication、DasPixel 通过 RunUAT BuildPlugin 打包到时间命名目录，自动补齐依赖、排序、重试并备份式部署到引擎；用户要求打包 Das 插件或指定目录打包这组 UE 插件时使用。
user-invocable: false
---

# Unreal 插件打包

1. 获取包含全部固定插件的源目录、目标 Unreal Engine 目录、打包输出根目录；只询问尚未提供且无法从上下文确定的路径。
2. 只打包同级 `plugin_pack_config.json` 固定的 `DasUnreal`、`cesium-unreal`、`DasApplication`、`DasPixel`，不要通过命令行增删插件。运行：

   ```powershell
   python "<本 Skill 目录>\pack_ue_plugins.py" "<插件源目录>" "<引擎目录>" "<输出根目录>"
   ```

   只验证计划时追加 `--dry-run`；不部署到引擎时追加 `--no-install`。
3. 脚本创建 `yyyyMMddHHmm` 时间目录，解析模块依赖并排序，通过 `RunUAT.bat BuildPlugin -TargetPlatforms=Win64 -Rocket` 打包。它会备份并补齐源 `.uplugin` 的缺失依赖、根据 UBT 依赖警告修复后重试，成功后把插件部署到 `Engine/Plugins/Marketplace`；已有目录改名为 `.backup-<时间>`，不要删除备份。
4. 打包失败时读取脚本报告的 UTF-8 日志，定位第一条 UHT、UBT 或编译器错误，仅修改对应插件源代码或 `Build.cs` 后原命令重跑，直到固定清单全部成功。缺少 SDK、工具链、磁盘权限或错误需要改变公共 API/运行行为时停止并报告，不猜测修复。
5. 报告时间目录、每个插件包目录、引擎部署目录、备份目录和剩余警告。
