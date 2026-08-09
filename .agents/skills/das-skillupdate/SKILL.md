---
name: das-skillupdate
description: 从用户目录克隆或更新 SkillsWorkBase，并重新部署 Claude/Codex 的 Das Skills；用户要求刷新、更新、同步或重新部署 dasSkill、Das Skill 或 SkillsWorkBase 时使用。
user-invocable: false
---

- 使用 Python 3 执行本文件同级的 `update_skills.py`。
- 脚本默认在 `%USERPROFILE%\SkillsWorkBase` 克隆或快进更新仓库，再调用仓库根目录的 `ClaudeSkill部署.bat --no-pause`。
- 保留本地修改；脚本失败时报告原始错误，不要强制重置或继续部署。
