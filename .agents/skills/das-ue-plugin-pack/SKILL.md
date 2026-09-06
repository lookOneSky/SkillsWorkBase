---
name: das-ue-plugin-pack
description: 用户要求打包 Das 插件，或打包 DasUnreal、cesium-unreal、DasApplication、DasPixel 这组 Unreal Engine 插件时使用。
user-invocable: false
---

# Unreal 插件打包

在 Windows 上按依赖顺序把固定的四个插件通过 `RunUAT BuildPlugin` 打包到时间命名目录，每个插件成功后立即复制到引擎并保存进度。

1. 获取包含全部固定插件的源目录、目标 Unreal Engine 目录、打包输出根目录；只询问尚未提供且无法从上下文确定的路径。
2. 只打包同级 `plugin_pack_config.json` 固定的 `DasUnreal`、`cesium-unreal`、`DasApplication`、`DasPixel`，不要通过命令行增删插件。运行：

   ```powershell
   python "<本 Skill 目录>\pack_ue_plugins.py" "<插件源目录>" "<引擎目录>" "<输出根目录>"
   ```

   只验证计划时追加 `--dry-run`。实际打包固定将每个成品复制到引擎，不提供跳过复制的选项；固定插件相互依赖，前序插件必须进入引擎后，后续插件才能正确打包。
3. 脚本创建 `yyyyMMddHHmm` 时间目录，解析模块依赖并排序，通过 `RunUAT.bat BuildPlugin -TargetPlatforms=Win64 -Rocket` 逐个打包。它会在修改源 `.uplugin` 前创建 `.autofix.bak`、补齐缺失依赖，并根据 UBT 依赖警告修复后重试；成品复制到 `Engine/Plugins/Marketplace`，目标同名插件目录已存在时直接删除再放入新成品，不保留备份。
4. 每个插件成功部署后立即更新 `_package-summary.json`。打包失败时读取 UTF-8 日志，定位第一条 UHT、UBT 或编译器错误，仅修改对应插件源代码或 `Build.cs`；修复后执行脚本输出的 `[继续命令]`，使用 `--resume <时间目录>` 校验并跳过已完成插件，从失败插件继续。缺少 SDK、工具链、磁盘权限或错误需要改变公共 API/运行行为时停止并报告，不猜测修复。
5. 报告时间目录、每个插件包目录、引擎部署目录和剩余警告。
