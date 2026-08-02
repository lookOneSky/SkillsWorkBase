---
name: creating-portable-skills
description: 创建或修改可部署到 Claude 的 Codex Skill。处理 SKILL.md 时使用。
---

- 仅维护 `.agents/skills/<name>/`。
- YAML 仅含 `name`、`description`；`name` 不超过 64 字符，只用小写字母、数字和连字符，不含 `anthropic`、`claude`；`description` 不超过 1024 字符，说明功能与触发条件。
- Skill要尽量简洁，而不是完整。
