---
name: das-permissions
description: 通过 /das-permissions 确保 Python 3 可用，为 Claude Code 项目开启完整文件与命令权限，并为 Claude Code 或 Codex 配置本地网络代理；Codex 仅配置代理。
disable-model-invocation: true
allowed-tools: Bash
---

# 权限与代理配置

仅在用户输入 `/das-permissions` 时执行。先定位 Python 3；未安装时，若 `winget` 可用，自动执行 `winget install --id Python.Python.3.12 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity --proxy http://127.0.0.1:10808`。安装成功后重新定位解释器并继续；`winget` 不可用或安装失败时直接报告。然后根据当前宿主运行同级脚本。

Claude Code：

```powershell
python "${CLAUDE_SKILL_DIR}/configure_permissions.py" claude "<当前项目根目录>"
```

脚本幂等更新 `<项目根目录>/.claude/settings.local.json`，保留无关配置，并设置：

- `env.HTTP_PROXY` 与 `env.HTTPS_PROXY` 为 `http://127.0.0.1:10808`
- `skipDangerousModePermissionPrompt: true`
- `permissions.defaultMode: "bypassPermissions"`
- 通用文件、编辑与命令工具允许规则
- 当前用户临时目录下的 `claude` 目录为额外文件目录

Codex：

```powershell
python "<当前 Skill 目录>/configure_permissions.py" codex
```

脚本幂等更新 `$CODEX_HOME/config.toml`；未设置 `CODEX_HOME` 时更新 `~/.codex/config.toml`。仅在 `[shell_environment_policy.set]` 中设置 `HTTP_PROXY` 与 `HTTPS_PROXY`，不修改 Codex 的文件权限、审批或沙箱配置。

文件或父目录不存在时自动创建。脚本失败时不要手工覆盖原配置；先修复其报告的无效 JSON、TOML 或字段类型。
