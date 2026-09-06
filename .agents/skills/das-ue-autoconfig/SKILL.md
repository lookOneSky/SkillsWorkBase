---
name: das-ue-autoconfig
description: 用户输入 `/das-ue-autoconfig` 时使用。
disable-model-invocation: true
---

# Unreal 自动配置

为 Unreal Engine 项目开启 Python 远程执行：写入 `Config/DefaultEngine.ini` 的 `bRemoteExecution=True`，并在 `.uproject` 启用 `PythonScriptPlugin`。

仅在用户输入 `/das-ue-autoconfig`，或其他 Skill 明确要求配置 Python 远程执行时执行；不要在 UE 相关任务开始前自动运行，同一会话内成功过也不再重复运行。其他 Skill 需要时直接运行本 Skill 同级的脚本：

```powershell
python "<本 Skill 目录>\configure_ue_python.py" "<项目.uproject 或项目目录>"
```

- 省略路径参数时从当前项目工作目录（不是用户目录中的 Skill 安装目录）递归查找唯一 `.uproject`；未找到或有多个时脚本报错，向用户确认后再传入具体路径。
- 脚本幂等：两处配置都已满足时不写文件，输出 `[配置] 已是目标状态`。
- 输出 `[提示] 编辑器正在运行` 时，告诉用户需重启编辑器才生效；脚本不会关闭或重启编辑器。
- 脚本报错时直接报告，不要改为手工编辑配置。
