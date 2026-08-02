---
name: das-unreal-mcp
description: 自动配置当前 Unreal Engine 项目的 MCP；用户要求为当前 Unreal 项目配置、安装或修复 MCP 时使用。
user-invocable: false
---

# Unreal MCP

运行：

```powershell
python "<本 Skill 目录>\configure_unreal_mcp.py"
```

脚本会从当前项目工作目录（不是用户目录中的 Skill 安装目录）递归查找唯一的 `.uproject` 并完成配置。脚本报错时直接报告，不要改为手工配置。
