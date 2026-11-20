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

`Shift+Tab` 切换 Plan／默认模式，新 Codex 窗口默认进入 Plan。Plan 快捷键保存在 `$CODEX_HOME/keybindings.json`，未设置 `CODEX_HOME` 时使用 `~/.codex`。

脚本根据 VS Code 扩展注册信息定位插件，不固定用户名、插件版本或资源文件哈希。默认 Plan 通过修改插件本地资源实现；写入前备份，重复执行不重复修改。插件更新后可再次运行。遇到 `Shift+Tab` 占用、无效配置或不兼容的插件代码结构时停止，不要改为手工覆盖。

用 `--extensions-dir "<扩展目录>"` 或 `--extension-dir "<插件目录>"` 指定自定义扩展路径。用 `--codex-home "<Codex 配置目录>"` 指定配置位置，后续检查沿用这些参数。

只检查、不修改：

```powershell
python "<本 Skill 目录>\configure_codex.py" --check
```

检查通过返回 0，需要初始化返回 2，操作失败返回 1。用户要求撤销时，使用初始化结果中的备份目录：

```powershell
python "<本 Skill 目录>\configure_codex.py" --restore "<备份目录>"
```

脚本执行后由 AI 负责校验和完善：

1. 用相同参数运行 `--check`，核对退出码、`checks` 和 `pending_files`，并确认磁盘中的 Plan 快捷键和默认模式。
2. 若检查失败，AI 分析问题，修复本技能脚本，运行 `python "<本 Skill 目录>\test_configure_codex.py"` 在隔离目录验证，再重新运行初始化和检查。所有配置改动均由脚本完成，不用手工修改目标文件绕过问题。
3. 若仍未完成，报告具体未完成项、影响文件、执行命令、退出码、错误信息、已尝试的修复及待优化的脚本逻辑，供后续改进；明确哪些已完成、哪些未完成。需要重载后才能验证的界面行为应明确标注为待验证。

完成后报告结果与备份位置。发生修改时提示在 VS Code 执行 `Developer: Reload Window` 后生效；不要自动关闭或重载正在使用的窗口。
