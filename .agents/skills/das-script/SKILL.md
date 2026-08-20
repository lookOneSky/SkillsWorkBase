---
name: das-script
description: 规范脚本的实现与入口。创建或修改 Windows 自动化脚本、批处理入口、命令行工具或 Skill 内置脚本时使用。
user-invocable: false
---

- 脚本优先使用 Python 3；若仅需很简短的 `.bat` 即可完成，则只实现 `.bat`，不创建 Python 脚本。
- 普通 Windows 自动化脚本使用 Python 时，通过 `.bat` 提供入口。
- Skill 内置脚本直接在该 Skill 的 `SKILL.md` 中记录执行命令；Python 实现不再创建 `.bat` 入口。
