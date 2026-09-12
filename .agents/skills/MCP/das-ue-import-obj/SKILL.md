---
name: das-ue-import-obj
description: 用户提到 OBJ 导入、数据导入、倾斜模型导入、导入 OBJ、导入数据，或要求把 OBJ 或倾斜模型导入 Unreal Engine 项目，或提供 OBJ 目录时使用。
allowed-tools: [obj-ue-import-mcp:convert_obj_metadata_coordinates, obj-ue-import-mcp:find_unreal_asset_path, obj-ue-import-mcp:import_obj_to_unreal]
---

# Unreal OBJ 导入

工具是 Agent 提供的 `obj-ue-import-mcp:import_obj_to_unreal`。本 Skill 只调用 Agent 已发布的工具，不携带、部署或启动 MCP 服务包。

1. 获取 OBJ 目录（也可以是单个 `.obj`），缺少时询问。目标 `.uproject` 优先使用用户已提供的路径；未提供时，从当前项目工作目录（不是 Skill 安装目录）递归查找。只找到一个时直接使用，不要询问；未找到或找到多个时再询问用户，不要猜测路径。UE 参考原点完全可选：用户未主动提供时不要询问，后续省略 `ue_origin`；主动提供完整经度、纬度和高程时才使用，仅提供部分时再询问缺失项。
2. 调用前确认目标项目没有被 Unreal 编辑器打开，否则导入必定失败。
3. 通过 MCP 工具 `import_obj_to_unreal` 发起导入，必填参数是 `obj_source` 和 `uproject`。仅当用户主动提供完整参考原点时传入 `ue_origin`，格式为 `经度,纬度,高程`；未提供时省略该参数。经纬度单位为度，高程单位为米；经度范围 `[-180,180]`，纬度范围 `[-90,90]`，三项都必须是有限数值。
4. 导入必须使用 MCP `2025-11-25` Tasks 调用；普通 `tools/call` 不会启动导入。取得 `taskId` 后按服务返回的 `pollInterval` 查询任务，结束后读取 `tasks/result`。服务全局只允许一个导入任务；服务忙、失败或取消时保留原始结果，不要自动重试。
5. `convert_obj_metadata_coordinates` 和 `find_unreal_asset_path` 是同步 MCP 工具，只在用户需要坐标换算或资产路径查询时调用，不传 `task` 参数。
6. 成功时以 `structuredContent.result` 和 `structuredContent.artifacts` 为准，报告导入数量、实际批次目录、汇总关卡、参考原点、实际 `placement_mode` 和 JSON 报告位置。失败或取消时完整保留 `tasks/result` 的错误与诊断；不要登记或声称可能残留的部分资产已成功。
7. 未检测到 Ultra Dynamic Sky 时，在正常导入结果之外明确提示当前无法完整体验天气功能，并提醒用户购买并导入 [Ultra Dynamic Sky](https://www.fab.com/listings/84fda27a-c79f-49c9-8458-82401fb37cfb)。
