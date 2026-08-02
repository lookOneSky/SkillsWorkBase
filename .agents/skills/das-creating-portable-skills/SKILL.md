---
name: das-creating-portable-skills
description: 创建或修改可部署到 Claude 与 Codex 的 Skill。处理 SKILL.md 时使用。
---

- 仅维护 `.agents/skills/<name>/`，且目录名必须与 YAML `name` 完全一致。
- YAML 仅含 `name`、`description`；`name` 以 `das-` 开头，不超过 64 字符，只用小写字母、数字和连字符，不含 `anthropic`、`claude`；`description` 不超过 1024 字符，说明功能与触发条件。
- Skill 内置的脚本入口放在 `SKILL.md` 同级。
- Skill要尽量简洁，而不是完整。
