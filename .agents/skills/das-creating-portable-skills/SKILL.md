---
name: das-creating-portable-skills
description: 用户要求创建或修改 Skill 时使用。
user-invocable: false
---

# 创建可移植 Skill

- 仅维护 `.agents/skills/<name>/`，目录名必须与 YAML `name` 完全一致；这里的 Skill 会部署到 Claude、Codex、WorkBuddy 与 SpatialMind。
- `name` 以 `das-` 开头，不超过 64 字符，只用小写字母、数字和连字符，不含 `anthropic`、`claude`。
- `description` 只写触发条件，句式为「……时使用。」，不写功能、步骤、参数或约束，不超过 1024 字符。
- 能力、流程、约束和脚本命令一律写在 `SKILL.md` 正文。
- 调用方式二选一，不要同时设置：自动触发专用 Skill 设 `user-invocable: false`，手动调用专用 Skill 设 `disable-model-invocation: true`。
- Skill 内置的脚本入口放在 `SKILL.md` 同级。
- Skill 要尽量简洁，而不是完整。
