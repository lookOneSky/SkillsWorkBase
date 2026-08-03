---
name: das-ue-plugin-share
description: 使用 Windows 目录 Junction 把外部 Unreal Engine Plugin 目录共享到当前项目；用户提供 Plugin 目录并要求共享、链接、复用或通过 mklink /J 放入当前 Unreal 项目时使用。
user-invocable: false
---

# Unreal Plugin 共享

1. 获取原始 Plugin 目录；只询问尚未提供的路径。
2. 在 Unreal 项目工作目录运行：

   ```powershell
   python "<本 Skill 目录>\share_ue_plugin.py" "<Plugin 目录>"
   ```

3. 脚本会定位唯一的 `.uproject`，并执行 `mklink /J "<项目>\Plugins\<Plugin 目录名>" "<原始目录>"`。
4. 报告原始目录和链接目录；脚本报错时直接报告，不要删除或覆盖已有目标。
