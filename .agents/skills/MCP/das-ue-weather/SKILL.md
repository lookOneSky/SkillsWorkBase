---
name: das-ue-weather
description: 用户提到设置天气、切换天气、调天气、下雨、下雪、起雾、晴天、阴天、沙尘，或提到设置时间、调时间、改成几点、日出、日落、黄昏、夜晚、白天，或要求设置场景、关卡、编辑器、Unreal 项目的时间或天气时使用。
allowed-tools: [ue-weather-mcp:set_unreal_weather]
---

# Unreal 时间与天气

工具是 Agent 提供的 `ue-weather-mcp:set_unreal_weather`。本 Skill 只调用 Agent 已发布的工具，不携带、部署或启动 MCP 服务包。

1. 目标 `.uproject` 优先使用用户已提供的路径；未提供时，从当前项目工作目录（不是 Skill 安装目录）递归查找。只找到一个时直接使用，不要询问；未找到或找到多个时再询问用户，不要猜测路径。`time`、`time_of_day`、`sunrise` 三种时间设置互斥，可任选一种并与 `preset` 同时设置；四项中至少给一项，只下发用户明确要求的项。
2. 时间优先用 `time` 传 `HH:MM[:SS]`；只有用户明确给出 UDS 线性刻度时才用 `time_of_day`（范围 `0-2400`，`09:30` 对应 `950`）。用户要求当前关卡位置的今日日出时传 `sunrise: true`。
3. 天气用 `preset` 传天气类型、中文名或标准预设名：`Clear_Skies`、`Partly_Cloudy`、`Cloudy`、`Overcast`、`Foggy`、`Rain_Light`、`Rain`、`Rain_Thunderstorm`、`Snow_Light`、`Snow`、`Snow_Blizzard`、`Sand_Dust_Calm`、`Sand_Dust_Storm`。设置预设会清除手动天气覆盖。
4. 默认只在编辑器中预览，省略 `save` 或传 `false`；只有用户明确要求保存关卡或保存修改时才传 `save: true`。`outliner_folder` 和 `timeout_seconds` 仅在用户明确需要时传入。
5. 通过 MCP `2025-11-25` Tasks 调用工具；普通 `tools/call` 不会启动设置。取得 `taskId` 后按 `pollInterval` 查询任务，结束后读取 `tasks/result`。服务全局只允许一个天气任务；服务忙、失败或取消时保留原始结果，不要自动重试。
6. 成功时以 `structuredContent.result` 和 `structuredContent.artifacts` 为准，按报告中各任务的 `before` / `after` 说明实际改动，并提供 JSON 报告位置。失败或取消时完整保留 `tasks/result` 的错误与诊断，不要声称可能已经写入编辑器的部分状态成功。
7. 结果明确表示关卡里没有 Ultra Dynamic Sky 或 Ultra Dynamic Weather、工程里也找不到对应蓝图时，保留原始错误，并提示当前无法完整体验天气功能，提醒用户购买并导入 [Ultra Dynamic Sky](https://www.fab.com/listings/84fda27a-c79f-49c9-8458-82401fb37cfb)。仅缺少天气预设资产或发生其他错误时不要给出购买提醒。
