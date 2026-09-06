---
name: das-ue-launch
description: 用户输入 `/das-ue-launch` 时使用。
disable-model-invocation: true
---

# Unreal 启动编辑器

检测指定 `.uproject` 的 Unreal 编辑器实例：已在运行就不重复启动，未运行则启动它；两种情况都返回后续 Python 接入 UE 所需的实例信息。仅支持 Windows。

仅在用户输入 `/das-ue-launch`，或其他 Skill 明确要求启动编辑器时执行；不要在 UE 相关任务开始前自动运行。其他 Skill 需要时直接运行本 Skill 同级的脚本：

```powershell
python "<本 Skill 目录>\launch_ue_editor.py" "<项目.uproject 或项目目录>"
```

- 省略路径参数时从当前项目工作目录（不是用户目录中的 Skill 安装目录）递归查找唯一 `.uproject`；未找到或有多个时脚本报错，向用户确认后再传入具体路径。
- 输出 `[运行中]` 表示已有实例，脚本不会重复启动，也不会关闭或重启编辑器；输出 `[启动]` 表示已拉起新进程。
- 启动时自动挑选项目与插件模块清单、BuildId 和 DLL 均齐全的编辑器配置：优先 Development，否则取最新 Editor target 对应的可用配置（如 DebugGame）。`[配置]` 行显示所选配置；`--config DebugGame` 可强制新启动的构建配置，找不到候选时报错。已有实例仍返回实际进程的配置。
- 全部候选的模块都不完整时仍尝试启动，并输出 `[提示] <配置> 模块不完整`。此时让用户在 IDE 里编译对应的 Editor 配置，不要在脚本里绕过校验、修改 BuildId 或触发编译。DebugGame 校验复用引擎默认 `UnrealEditor.modules`（UE4 为 `UE4Editor.modules`）；纯内容插件及没有项目 Binaries 的模板/蓝图工程不要求项目模块清单。
- 脚本默认不等待启动完成。需要等到编辑器可用再做下一步时加 `--wait <秒>`，出现 `[就绪]` 才说明主窗口已显示，`[超时]` 表示仍在启动。
- 末行 `UE_LAUNCH_RESULT=` 后是单行 JSON：`status`(running/launched)、`ready`、`project`、`engine_root`、`editor`、`process_ids`、`python_remote_execution`（远程执行开关与组播端点）、`editor_startup_map`、`game_default_map`、`level_count`、`levels`（Content 下的 `/Game` 关卡索引，含 `name`/`package`/`object_path`）。后续 Python 操作按这份 JSON 接入实例、选目标关卡。
- 关卡超过 30 个时 stdout 只给前 30 条并置 `levels_truncated=true`；需要完整索引就加 `--json "<路径>"`，文件里是全量结果，路径同时回填在 `levels_file`。
- `python_remote_execution.enabled` 为 `false` 时，远程执行没开，先运行 das-ue-autoconfig 再重启编辑器。
- 引擎按 `.uproject` 的 `EngineAssociation` 定位；定位失败时用 `--engine-root "<引擎根目录>"` 指定。
- 追加编辑器命令行参数写在 `--` 之后，例如 `-- -log`。
- 脚本报错时直接报告，不要改为手工启动。

JSON 还包含以下构建信息（stdout 和 `--json` 文件一致）：

| 字段 | 含义 |
| --- | --- |
| `configuration` | 选中或实际运行的编辑器构建配置，如 `Development`、`DebugGame` |
| `modules_ready` | 模块校验通过为 `true`；已有编辑器进程时为 `true` |
| `modules_problems` | 模块问题列表，最多 5 条；校验通过或已有实例时为空 |
