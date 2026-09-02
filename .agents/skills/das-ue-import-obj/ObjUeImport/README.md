# obj_ue_import.exe 命令行说明

把一个目录里的 OBJ 批量导入 Unreal 项目，再按配置批量修改导入产生的纹理属性。
程序只启动一次 `UnrealEditor-Cmd.exe`，在同一个编辑器会话里先跑 `import_obj.py`、再跑 `modify_texture.py`。

不带下列参数启动（例如双击）会打开图形界面；带参数则是纯命令行模式，不弹窗，便于批处理。

## 前置条件

- 目标 Unreal 项目当前**没有被编辑器打开**，否则 commandlet 会因为文件占用失败。
- 程序目录下存在 `extern\ObjDynamicImport`（含 `import_obj.py`、`import_obj.json`、`DasMaterial`）与 `extern\ModifyTexture`（含 `modify_texture.py`、`modify_texture.json`）。发布包已自带。
- 能定位到 `UnrealEditor-Cmd.exe`，见下文「引擎定位顺序」。
- 不需要在本机安装 Python：脚本由 Unreal 自带的 Python 执行。

## 用法

```powershell
obj_ue_import.exe --ue-import <OBJ目录> <项目.uproject> [选项]
```

两个位置参数都必填，顺序固定。`--import` 是 `--ue-import` 的简写。

| 位置参数 | 说明 |
| --- | --- |
| `<OBJ目录>` | 递归查找其中所有 `.obj`；也可以直接给单个 `.obj` 文件 |
| `<项目.uproject>` | 目标 Unreal 项目 |

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `--import-config <json>` | 程序目录下的 `extern\ObjDynamicImport\import_obj.json` | 导入配置 |
| `--texture-config <json>` | 程序目录下的 `extern\ModifyTexture\modify_texture.json` | 纹理配置 |
| `--destination <UE目录>` | 导入配置里的 `destination_root` | 覆盖导入目标，支持 `{timestamp}`、`{date}` |
| `--editor <路径>` | 按 `.uproject` 自动定位 | 指定 `UnrealEditor-Cmd.exe` |
| `--max-texture-size <N>` | 纹理配置里的值 | `0`（不限制）或 2 的幂 |
| `--virtual-texture <on\|off>` | 纹理配置里的值 | 虚拟纹理流送 |
| `--skip-texture` | 关闭 | 只导入 OBJ，不修改纹理 |
| `--help`, `-h` | — | 打印用法 |

## 示例

```powershell
:: 全部用默认配置：导入 + 改纹理
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject"

:: 只导入，不动纹理
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --skip-texture

:: 覆盖纹理属性，不改 JSON
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --max-texture-size 1024 --virtual-texture off

:: 换一个导入目标目录（按天分批）
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --destination "/Game/Tiles/{date}"

:: 指定引擎，并把完整日志写到文件
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" ^
    --editor "C:\Program Files\Epic Games\UE_5.3\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" > import.log
```

## 运行流程

1. 校验输入、统计 `.obj` 数量、定位引擎——任何一项不通过都会在启动 Unreal 之前失败。
2. 把 `extern\ObjDynamicImport\DasMaterial` 覆盖复制到 `<项目>\Content\DasMaterial`。
3. 在 `%TEMP%\ObjUeImport\<时间戳>\` 生成两份临时配置：
   - `import_obj.json`：`project_file` 改成本次项目，`destination_root` 里的 `{timestamp}` 已展开成实际时间戳；
   - `modify_texture.json`：`content_directory` 填成同一个批次目录，纹理属性按命令行覆盖。
   出错时可以直接打开这两个文件核对实际生效的配置。
4. 启动一次 `UnrealEditor-Cmd.exe`，依次执行导入与改纹理，全过程日志实时转发到标准输出。

导入结果默认落在 `/Game/ObjImport/<YYYYMMDD_HHMMSS>`，对应物理目录 `<项目>\Content\ObjImport\<YYYYMMDD_HHMMSS>`；静态模型前缀 `SM_`，材质以 `/Game/DasMaterial/MI_Model` 为父级生成材质实例。每个 OBJ 导入后会等待 StaticMesh 构建及 DDC 写入完成，再保存资产。

## 引擎定位顺序

按顺序取第一个真实存在的 `UnrealEditor-Cmd.exe`：

1. `--editor` 指定的路径。
2. 导入配置里的 `unreal_editor_cmd`（相对路径按 JSON 所在目录解析）。
3. 由 `.uproject` 的 `EngineAssociation` 推导：
   - `{GUID}` 形式（源码构建）→ 注册表 `HKEY_CURRENT_USER\SOFTWARE\Epic Games\Unreal Engine\Builds`；
   - `5.3` 这类版本号 → `C:\ProgramData\Epic\UnrealEngineLauncher\LauncherInstalled.dat` 中 `AppName` 为 `UE_5.3` 的安装位置 → 注册表 `HKEY_LOCAL_MACHINE\SOFTWARE\EpicGames\Unreal Engine\5.3\InstalledDirectory` → `C:\Program Files\Epic Games\UE_5.3`。
4. 从 `.uproject` 逐级向上找 `Engine\Binaries\Win64\UnrealEditor-Cmd.exe`（工程放在引擎源码树里的情况）。

全部落空时会报错并列出所有查找过的路径，此时用 `--editor` 显式指定。

## 配置文件里哪些字段生效

`import_obj.json`（其余字段的含义见 `extern\ObjDynamicImport\README.md`）：

- `destination_root`、`asset_name_prefix`、`parent_material`、`build_static_mesh_ddc`、`import_task`、`obj_import_ui`、`static_mesh_import_data`、`texture_import_data` 等由 `import_obj.py` 使用；`build_static_mesh_ddc` 默认为 `true`；
- `enabled_plugins` 拼成 `-EnablePlugins=`，`commandlet_arguments` 原样追加到命令行。程序会自动补齐缺失的 `-unattended`、`-nosplash`、`-stdout`、`-FullStdOutLogOutput`、`-UTF8Output`、`-AllowCommandletRendering`——少了前几个会看不到日志或卡在无人应答的弹窗上，少了 `-UTF8Output` 则脚本里的中文会被逐字输出成 `?`；少了 `-AllowCommandletRendering` 则 `FApp::CanEverRender()` 为 false，`UTexture::CachePlatformData` 直接跳过，纹理不会写入 DDC，编辑器下次打开会把所有纹理重建一遍（`import_obj.py` 启动时会检查这个参数，缺失直接报错）；
- `cleanup.unload_after_import`（缺省 `true`）每导入完一批就卸载这批资产并回收内存，`cleanup.interval`（缺省 `1`）是攒多少个 OBJ 卸载一次。整段 `cleanup` 可以省略；`import_task.save=false` 时不会卸载，避免丢掉没保存的改动；
- `project_file` 与 `destination_root` 每次运行都会被临时配置覆盖，改这两项对本工具无效——用位置参数和 `--destination`。

`modify_texture.json`：

- `texture_properties` 支持 `max_texture_size` 与 `virtual_texture_streaming`，至少要有一项；
- `recursive` 缺省为 `true`；
- `cleanup.unload_processed`（缺省 `true`）在处理过程中分批卸载已改完的纹理，`cleanup.interval`（缺省 `50`）是攒多少张卸载一次。整段 `cleanup` 可以省略；调小更省内存、但 GC 更频繁，4K 纹理建议 30~50；
- `content_directory` 每次运行都会被覆盖成本批次的导入目录。

导入的资产带 `RF_Standalone` 标记，编辑器里的常规 GC 不会回收，因此不做清理时内存会随资产数量线性上涨——一批几千张 4K 纹理可以吃掉几十 GB。清理走的是 `UnloadPackages`（先保存、再清标记、再 GC），仍被引用的资产会被安全跳过并打印 `OBJ_IMPORT_UNLOAD_SKIPPED=`。

## 日志标记

完整的 Unreal 日志会原样转发，其中这些标记可以用来判断进度与结果：

| 标记 | 含义 |
| --- | --- |
| `OBJ_IMPORT_DDC=` | 一个 StaticMesh 的构建及 DDC 请求已完成，后面是 LOD 和三角形统计 |
| `OBJ_IMPORT_RESULT=` | 一个 OBJ 导入完成，后面是该次导入的 JSON 明细 |
| `OBJ_IMPORT_BATCH_RESULT=` | 整批导入完成，含批次目录与文件数 |
| `OBJ_IMPORT_ERROR=` | 导入脚本报错，失败信息会被提取成最终错误 |
| `OBJ_IMPORT_UNLOAD_SKIPPED=` | 导入阶段有资产没能卸载（仍被引用），只影响内存占用，不影响导入结果 |
| `[TexturePropertyBatch]` | 改纹理阶段的日志前缀 |

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | 执行失败（校验不通过、引擎找不到、Unreal 返回非 0 等） |
| `2` | 参数非法，会同时打印用法 |

## 注意事项

- 程序是 WIN32 子系统，未重定向时会附加到调用方的控制台；重定向到文件同样有效。
- PowerShell 不会等待 WIN32 子系统程序退出，`&` 直接调用会立刻返回提示符。需要等待时重定向输出、接管道，或用 `Start-Process -Wait`。
- 首次导入后若要覆盖同名资产，把 `import_obj.json` 的 `import_task.replace_existing` 与 `replace_existing_settings` 改为 `true`。
- 「取消」会先 `terminate` 再 `kill` 编辑器进程；此时已经写入项目的资产不会回滚。
