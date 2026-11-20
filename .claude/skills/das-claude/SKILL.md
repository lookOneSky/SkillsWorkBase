---
name: das-claude
description: 用户要求初始化 Claude Code 的 VS Code 快捷键或恢复 Alt+K 时使用。
---

# Das-Claude

用 Python 3 执行同级脚本，恢复 VS Code 编辑器中的 Claude Code 快捷键：

```powershell
python "<本 Skill 目录>\configure_claude.py"
python "<本 Skill 目录>\configure_claude.py" --check
```

在文件编辑器中按 `Alt+K`，选中文本时插入文件及选中行的引用，未选中时插入当前文件引用。输入问题后发送。

脚本检查 Claude 扩展注册的命令，移除旧版 Codex 的两种 `Alt+K` 绑定和 Claude 的同键禁用规则。修改时在快捷键文件旁备份原件。通过 `--vscode-user-dir` 指定自定义 Profile 的用户配置目录，通过 `--extensions-dir` 指定自定义扩展目录。验证时沿用相同参数，`--check` 返回 0 表示已配置，2 表示需要配置，1 表示检查失败。
