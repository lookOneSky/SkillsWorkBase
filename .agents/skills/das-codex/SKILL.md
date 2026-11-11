---
name: das-codex
description: 用户输入 `/dasCodexInit` 或调用 `das-codex` 技能时使用。
disable-model-invocation: true
---

# Codex 初始化

将 `/dasCodexInit` 作为初始化指令，使用 Python 3 执行同级脚本：

```powershell
python "<本 Skill 目录>\configure_codex.py"
```

脚本为本机 VS Code 的 Codex 插件添加 `Shift+Tab`，切换 Plan／默认模式，并让新 Codex 窗口默认进入 Plan。快捷键保存在 `$CODEX_HOME/keybindings.json`；未设置 `CODEX_HOME` 时使用 `~/.codex`。保留已有快捷键和其他配置。

脚本根据 VS Code 扩展注册信息定位插件，不固定用户名、插件版本或资源文件哈希。默认 Plan 通过修改插件本地资源实现；写入前备份，重复执行不重复修改。插件更新后可再次运行。遇到快捷键冲突、无效配置或不兼容的插件代码结构时停止，不要改为手工覆盖。

自定义扩展目录时加 `--extensions-dir "<扩展目录>"`；指定某个插件安装目录时加 `--extension-dir "<插件目录>"`。可用 `--codex-home "<Codex 配置目录>"` 指定配置位置。

只检查、不修改：

```powershell
python "<本 Skill 目录>\configure_codex.py" --check
```

检查通过返回 0，需要初始化返回 2，操作失败返回 1。用户要求撤销时，使用初始化结果中的备份目录：

```powershell
python "<本 Skill 目录>\configure_codex.py" --restore "<备份目录>"
```

完成后报告结果与备份位置。发生修改时提示在 VS Code 执行 `Developer: Reload Window` 后生效；不要自动关闭或重载正在使用的窗口。
