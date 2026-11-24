---
name: das-antigravity
description: 用户要求配置 VS Code 中发送至 Antigravity 的 Alt+K 快捷键或调用 Das-AntiGravity 技能时使用。
user-invocable: false
---

# VS Code 的 Antigravity 快捷键

在 VS Code 中配置 Antigravity 扩展的 `Alt+K`：

- 有选中文本：`antigravity.insertSnippet`，条件为 `editorTextFocus && editorHasSelection`。
- 无选中文本：`antigravity.addFileToChat`，条件为 `editorTextFocus && !editorHasSelection && (resourceScheme == file || resourceScheme == vscode-remote)`，添加当前文件。

两者都将上下文添加到 Antigravity 聊天，提问由用户发送。目标是 VS Code 的 `google.google-antigravity` 扩展；用户指定 Antigravity 独立 IDE 时应另行核对其配置目录。

用 Python 3 执行同级脚本：

```powershell
python "<本 Skill 目录>\configure_antigravity.py"
python "<本 Skill 目录>\configure_antigravity.py" --check
```

默认修改 `%APPDATA%\Code\User\keybindings.json`。使用命名 Profile 或便携安装时，指定实际用户配置目录；自定义扩展目录可传入 `--extensions-dir`，执行和检查使用相同参数：

```powershell
python "<本 Skill 目录>\configure_antigravity.py" --vscode-user-dir "<包含 keybindings.json 的目录>" --extensions-dir "<扩展根目录>"
```

脚本从扩展注册信息定位版本，并核对 `package.json` 中的两个命令，不固定用户名或扩展版本。替换 `Alt+K` 上旧的 Codex、Claude 和 Antigravity 规则，同时加入 `-claude-vscode.insertAtMention`／`editorTextFocus` 以解除 Claude 的默认占用，再将上述两条目标规则置于末尾。

增量编辑 JSONC，保留其他规则、注释、BOM 和换行，包括已有的无障碍与按键记录 `Shift+Alt+K` 规则及其 `Alt+K` 禁用项。修改前备份原文件，重复执行不重复写入。`--check` 只读：返回 0 表示已配置，2 表示需要配置，1 表示失败；无效配置或缺少扩展命令时不写入。

执行后运行 `--check`，报告配置文件与备份路径。当前已正确配置时直接报告检查通过；实际按键行为由用户验证，不自动发送提问或重载窗口。

修改脚本后运行同级 `test_configure_antigravity.py`，在临时目录验证迁移、配置保留、备份和幂等行为。
