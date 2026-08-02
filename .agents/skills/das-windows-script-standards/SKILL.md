---
name: das-windows-script-standards
description: 规范 Windows 脚本的实现与入口。创建或修改 Windows 自动化脚本、批处理入口、命令行工具或 Skill 内置脚本时使用；Skill 内置 Python 脚本无需额外的 .bat。
---

- 所有 Windows 脚本使用 Python 实现。
- 普通 Windows 自动化脚本通过 `.bat` 调用。
- Skill 内置脚本不创建 `.bat`；在该 Skill 的 `SKILL.md` 中记录 Python 执行命令。
