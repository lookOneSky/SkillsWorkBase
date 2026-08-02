---
name: das-windows-script-standards
description: 规范 Windows 脚本的实现与入口。创建或修改 Windows 自动化脚本、批处理入口、命令行工具或 Skill 内置脚本时使用；Skill 内置 Python 脚本无需额外的 .bat。
---

- 所有 Windows 脚本使用 Python 实现。
- 普通 Windows 自动化脚本通过 `.bat` 调用。
- Skill 内置脚本不创建 `.bat`；在该 Skill 的 `SKILL.md` 中记录 Python 执行命令。
- 触发 Python 脚本时先定位已有 Python 3；若未安装且 `winget` 可用，执行 `winget install --id Python.Python.3.12 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity --proxy http://127.0.0.1:10808`，安装成功后重新定位解释器并继续；`winget` 不可用或安装失败时直接报告。
