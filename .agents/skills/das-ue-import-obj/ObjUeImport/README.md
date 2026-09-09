# obj_ue_import.exe 命令行说明

把一个目录里的 OBJ 批量导入 Unreal 项目，按配置批量修改导入产生的纹理属性，最后把整批静态模型汇总到一个关卡里。
程序按工程和插件模块选择一次兼容的 `UnrealEditor-*-Cmd.exe`，在同一个编辑器会话里依次跑 `import_obj.py`、`modify_texture.py`、`build_level.py`。

不带下列参数启动（例如双击）会打开图形界面；带参数则是纯命令行模式，不弹窗，便于批处理。

## 前置条件

- 目标 Unreal 项目当前**没有被编辑器打开**，否则 commandlet 会因为文件占用失败。
- 程序目录下存在 `das_ue_asset_path.exe`、`extern\ObjDynamicImport`（含导入脚本、普通 `DasMaterial` 与 `Weather\DasMaterial`）以及 `extern\ModifyTexture`。发布包已自带。
- 能定位到插件模块完整且 BuildId 匹配的 `UnrealEditor-*-Cmd.exe`，见下文「编辑器选择」。
- 可选：程序目录下有 `metadata_coords.exe` 与 `share\proj\proj.db`（发布包已自带），用于换算 `metadata.xml` 的经纬度；缺失只会打警告，不影响导入。
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
| `--editor <路径>` | 按工程与插件模块自动选择 | 指定 `UnrealEditor-*-Cmd.exe` |
| `--ue-origin <经度,纬度,高程>` | 未指定 | UE 参考原点，经纬度单位为度、高程单位为米 |
| `--max-texture-size <N>` | 纹理配置里的值 | `0`（不限制）或 2 的幂 |
| `--virtual-texture <on\|off>` | 纹理配置里的值 | 虚拟纹理流送 |
| `--skip-texture` | 关闭 | 只导入 OBJ，不修改纹理 |
| `--skip-level` | 关闭 | 不生成汇总本批次静态模型的关卡 |
| `--help`, `-h` | — | 打印用法 |

## 示例

```powershell
:: 全部用默认配置：导入 + 改纹理
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject"

:: 指定 UE 参考原点，由第一份 metadata.xml 计算整批模型偏移
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --ue-origin "108.2,22.6,30"

:: 只导入，不动纹理
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --skip-texture

:: 导入 + 改纹理，但不生成关卡（瓦块特别多、内存吃紧时用）
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --skip-level

:: 覆盖纹理属性，不改 JSON
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --max-texture-size 1024 --virtual-texture off

:: 换一个导入目标目录（按天分批）
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" --destination "/Game/Tiles/{date}"

:: 指定引擎，并把完整日志写到文件
obj_ue_import.exe --ue-import "D:\Obj" "D:\Proj\My.uproject" ^
    --editor "C:\Program Files\Epic Games\UE_5.3\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" > import.log
```

## 运行流程

1. 校验输入、统计 `.obj` 数量，按与 `das_ue_launcher.exe` 相同的规则定位引擎并选择插件兼容的 commandlet——任何一项不通过都会在启动 Unreal 之前失败。
2. 调用同目录的 `das_ue_asset_path.exe`，同时扫描工程、项目插件与当前引擎插件，检查 `UltraDynamicWeather_Parameters`。
3. 找到标准天气资产时启用插件、写入目录重定向并复制 `Weather\DasMaterial`；未找到时复制普通 `DasMaterial`。两者目标都是 `<项目>\Content\DasMaterial`。
4. 按 OBJ 路径稳定排序，找到第一份 `metadata.xml` 并换算经纬度；指定 `--ue-origin` 时同时计算整批模型的 UE 偏移。结果写成 `<批次目录>\DasDataInfo\metadata.json`，见下文「批次元数据」。
5. 在 `%TEMP%\ObjUeImport\<时间戳>\` 生成三份临时配置：
   - `import_obj.json`：`project_file` 改成本次项目，`destination_root` 里的 `{timestamp}` 已展开成实际时间戳，`batch_timestamp` 填成本次时间戳；
   - `modify_texture.json`：`content_directory` 填成同一个批次目录，纹理属性按命令行覆盖；
   - `build_level.json`：`destination_path` 填成同一个批次目录，`level_root` 填成该批次的 `DasDataInfo` 路径，`batch_timestamp` 填成本次时间戳；原点换算成功时另写入 `placement_offset`。
   出错时可以直接打开这三个文件核对实际生效的配置。
6. 启动选中的 `UnrealEditor-*-Cmd.exe`，依次执行导入、改纹理、建关卡，全过程日志实时转发到标准输出。

## 天气材质自动选择

天气版母材质引用旧目录 `/Game/UltraDynamicSky/...`。工具找到完整目录结构中的标志资产后，会从挂载点推导插件名、从资产路径推导 UDS 根目录，并在项目 `Config\DefaultEngine.ini` 幂等写入。例如 UDS 位于插件根目录时：

```ini
[CoreRedirects]
+PackageRedirects=(OldName="/Game/UltraDynamicSky",NewName="/UltraDynamicSky",MatchSubstring=true)
```

UDS 也可以位于插件子目录，例如标志资产为 `/DasAssetLibrary/UltraDynamicSky/Materials/Weather/UltraDynamicWeather_Parameters` 时，`NewName` 使用 `/DasAssetLibrary/UltraDynamicSky`。同时，工具会在 `.uproject` 中把挂载该内容的插件设为 `Enabled=true`，并为本次 commandlet 追加到 `-EnablePlugins=`。已有相同映射不会重复写入；同一 `OldName` 已指向其他目录时会在复制材质和启动 UE 前报错，不覆盖项目配置。

以下情况使用普通材质继续导入：没有标志资产、只有同名但目录结构不兼容的资产。检测 EXE 缺失、执行失败、输出损坏或出现多个兼容天气资产根目录属于检测失败，会终止导入。

导入结果默认落在 `/Game/ObjImport/<YYYYMMDD_HHMMSS>`，对应物理目录 `<项目>\Content\ObjImport\<YYYYMMDD_HHMMSS>`；静态模型前缀 `SM_`。文件名中的数字负号编码为 `neg`，数字正号仍按原规则省略（例如 `Tile_+0000_-0010.obj` -> `SM_Tile_0000_neg0010`）。工具会在导入前检查最终静态模型资产名是否重复，避免 `replace_existing=true` 静默覆盖。每个 OBJ 导入后会等待 StaticMesh 构建及 DDC 写入完成，再保存资产。

## 批次元数据（DasDataInfo）

启动 Unreal **之前**，程序会把 `.obj` 绝对路径按大小写不敏感方式稳定排序，再依次向上找 `metadata.xml`：

- **不看 `.obj` 自己所在的瓦块目录**——瓦块目录动辄成百上千，且从不带 `metadata.xml`；
- 每个 OBJ 只看第 2、3、4 级上级目录，近的优先。倾斜成果常见的 `<成果>\Data\<瓦块>\<瓦块>.obj` 布局里，`<成果>\metadata.xml` 正好落在第 3 级；
- 找到第一份后立即停止，不读取同批次中的其他 `metadata.xml`。第一份换算失败时也不会尝试下一份。

找到的 `metadata.xml` 交给同目录下的 `metadata_coords.exe` 换算成经纬度。指定参考原点后，实际调用会增加 `--ue-origin "经度,纬度,高程"`，输出的 `ue_esu_offset` 为 `X=东、Y=南、Z=上` 的 UE 厘米偏移。结果写入 `<批次目录>\DasDataInfo\metadata.json`：

界面中的经度、纬度、高程必须三项同时为空或同时填写；命令行也必须传三个有限数值。经度范围为 `[-180,180]`，纬度范围为 `[-90,90]`，输入非法会在导入前直接报参数错误。

```json
{
  "batch_timestamp": "20260906_170000",
  "destination_path": "/Game/ObjImport/20260906_170000",
  "obj_source": "D:/Data/Production_1",
  "metadata": [
    { "obj_count": 128, "file": "D:/Data/Production_1/metadata.xml", "source_crs": "EPSG:4545",
      "longitude": 108.19450716, "latitude": 22.59770511, "...": "其余字段与 metadata_coords.exe --json 一致" }
  ]
}
```

为兼容现有读取方，`metadata` 继续使用数组，但最多只有一项；`obj_count` 是本批次全部 OBJ 数量，因为选中的第一份 metadata 会用于整批模型。

这一步**只警告不中断**：没找到 `metadata.xml`、找不到 `metadata_coords.exe`、换算失败或偏移格式不兼容，都会继续导入，并让关卡退回原有 `origin_alignment`。成功算出的偏移在写 `metadata.json` 前已保存在内存中，因此 JSON 落盘失败不会影响模型放置。要用这个功能必须保证 `metadata_coords.exe` 和 `share\proj\proj.db` 与 `obj_ue_import.exe` 在同一个目录里（发布包默认如此）。

## 批次独立的母材质

导入开始前会把 `parent_material` 复制成 `<批次目录>\DasDataInfo\MI_Model_<YYYYMMDD_HHMMSS>`，本批次全部瓦块的材质实例都挂到这份副本上。之后调这份副本的参数只影响本批次，不会波及历史导入的数据。副本的 Parent 仍是原来的 `M_Model`。

副本、`metadata.json` 和关卡 `mapObjImport_<时间戳>.umap` 一起待在批次目录的 `DasDataInfo` 里，删批次时连同 `<时间戳>\` 目录一起删掉即可，不会碰到工具自带的 `Content\DasMaterial` 模板资产。

不需要这个行为时，把 `import_obj.json` 的 `batch_parent_material.enabled` 改成 `false`，所有批次会重新共用同一个 `parent_material`。想把副本放回批次目录外，给 `batch_parent_material.destination_root` 填一个绝对目录（例如老行为的 `/Game/ObjImport`）。

## 批次关卡

改纹理完成后新建关卡 `/Game/ObjImport/<YYYYMMDD_HHMMSS>/DasDataInfo/mapObjImport_<YYYYMMDD_HHMMSS>`，把批次目录里的全部 StaticMesh 放进去。所有 Actor 用**同一个**位置偏移量，因此瓦块之间的相对位置与 OBJ 原始坐标完全一致。指定参考原点且换算成功时直接使用 `metadata_coords.exe` 的偏移；否则由整批模型总包围盒计算，默认让底面中心贴到世界原点。

关卡阶段排在改纹理之后是必需的：关卡里的 Actor 会一直引用 StaticMesh、材质实例与纹理，先建关卡会让 `modify_texture.py` 的分批卸载全部落空，内存按全量纹理线性上涨。

## 编辑器选择

引擎根目录与 `das_ue_launcher.exe` 共用定位逻辑：

1. `--editor` 指定的路径。
2. 导入配置里的 `unreal_editor_cmd`（相对路径按 JSON 所在目录解析）。
3. 由 `.uproject` 的 `EngineAssociation` 推导：
   - `{GUID}` 形式（源码构建）→ 注册表 `HKEY_CURRENT_USER\SOFTWARE\Epic Games\Unreal Engine\Builds`；
   - `5.3` 这类版本号 → `C:\ProgramData\Epic\UnrealEngineLauncher\LauncherInstalled.dat` 中 `AppName` 为 `UE_5.3` 的安装位置 → 注册表 `HKEY_LOCAL_MACHINE\SOFTWARE\EpicGames\Unreal Engine\5.3\InstalledDirectory` → `C:\Program Files\Epic Games\UE_5.3`。
4. 从 `.uproject` 逐级向上找引擎源码树。

自动定位后读取工程 `Binaries\Win64\*.target`，检查工程和项目插件的 `.modules`、DLL
及其与引擎的 BuildId。优先选择完整的 Development，再选择其他完整配置，并映射到同配置的
`*-Cmd.exe`。所有配置都不完整或 commandlet 不存在时会在启动前列出每个候选的问题；不会通过
禁用插件绕过。显式路径同样执行兼容检查。

## 配置文件里哪些字段生效

`import_obj.json`（其余字段的含义见 `extern\ObjDynamicImport\README.md`）：

- `destination_root`、`asset_name_prefix`、`parent_material`、`build_static_mesh_ddc`、`import_task`、`obj_import_ui`、`static_mesh_import_data`、`texture_import_data` 等由 `import_obj.py` 使用；`build_static_mesh_ddc` 默认为 `true`；
- `data_info_directory`（缺省 `DasDataInfo`，只能是一级目录名）是批次目录下收 `metadata.json`、批次母材质与关卡的子目录，程序与脚本读的是同一个键；
- `batch_parent_material.enabled`（缺省 `true`）决定是否为本批次复制一份独立的母材质，`batch_parent_material.destination_root`（缺省空串 = 批次目录下的 `data_info_directory`；填绝对目录时支持 `{timestamp}` / `{date}`）是副本的存放目录。整段 `batch_parent_material` 可以省略；
- `enabled_plugins` 拼成 `-EnablePlugins=`，`commandlet_arguments` 原样追加到命令行。默认配置不再包含 `-DisablePlugins`；自定义配置显式提供时仍原样保留。程序会自动补齐缺失的 `-unattended`、`-nosplash`、`-stdout`、`-FullStdOutLogOutput`、`-UTF8Output`、`-AllowCommandletRendering`——少了前几个会看不到日志或卡在无人应答的弹窗上，少了 `-UTF8Output` 则脚本里的中文会被逐字输出成 `?`；少了 `-AllowCommandletRendering` 则 `FApp::CanEverRender()` 为 false，`UTexture::CachePlatformData` 直接跳过，纹理不会写入 DDC，编辑器下次打开会把所有纹理重建一遍（`import_obj.py` 启动时会检查这个参数，缺失直接报错）；
- `cleanup.unload_after_import`（缺省 `true`）每导入完一批就卸载这批资产并回收内存，`cleanup.interval`（缺省 `1`）是攒多少个 OBJ 卸载一次。整段 `cleanup` 可以省略；`import_task.save=false` 时不会卸载，避免丢掉没保存的改动；
- `project_file` 与 `batch_timestamp` 由程序写入临时配置；`destination_root` 同样会按本次参数展开，项目路径请使用位置参数，目标目录请使用 `--destination`。

`modify_texture.json`：

- `texture_properties` 支持 `max_texture_size` 与 `virtual_texture_streaming`，至少要有一项；
- `recursive` 缺省为 `true`；
- `cleanup.unload_processed`（缺省 `true`）在处理过程中分批卸载已改完的纹理，`cleanup.interval`（缺省 `50`）是攒多少张卸载一次。整段 `cleanup` 可以省略；调小更省内存、但 GC 更频繁，4K 纹理建议 30~50；
- `content_directory` 每次运行都会被覆盖成本批次的导入目录。

`build_level.json`：

- `level_root` 由 `obj_ue_import.exe` 覆盖成本批次的 `data_info_directory`，与 `level_name_prefix`（缺省 `mapObjImport_`）拼上批次时间戳得到关卡资产路径；直接运行脚本且未提供该字段时，默认使用 `destination_path/DasDataInfo`；
- `origin_alignment` 支持 `bottom_center`（缺省，XY 取包围盒中心、Z 取最小值）、`center`（XYZ 都取包围盒中心）、`xy_center`（只平移 XY，保留原始高程）；
- `placement_offset` 是可选的 `[X,Y,Z]` UE 厘米偏移，存在时优先于 `origin_alignment`；`obj_ue_import.exe` 只在原点换算成功后写入，未指定或失败时会从临时配置中移除；
- `outliner_folder`（缺省 `DasImport`）是本批次全部 Actor 在数据大纲中的目录，支持 `A/B` 多层，置空则不分组；
- `destination_path`、`level_root` 与 `batch_timestamp` 每次运行都会被临时配置写入，不需要也不应该手写。

导入的资产带 `RF_Standalone` 标记，编辑器里的常规 GC 不会回收，因此不做清理时内存会随资产数量线性上涨——一批几千张 4K 纹理可以吃掉几十 GB。清理走的是 `UnloadPackages`（先保存、再清标记、再 GC），仍被引用的资产会被安全跳过并打印 `OBJ_IMPORT_UNLOAD_SKIPPED=`。

## 日志标记

完整的 Unreal 日志会原样转发，其中这些标记可以用来判断进度与结果：

| 标记 | 含义 |
| --- | --- |
| `OBJ_IMPORT_BATCH_MATERIAL=` | 本批次母材质副本已创建，后面是源路径与副本路径 |
| `OBJ_IMPORT_DDC=` | 一个 StaticMesh 的构建及 DDC 请求已完成，后面是 LOD 和三角形统计 |
| `OBJ_IMPORT_RESULT=` | 一个 OBJ 导入完成，后面是该次导入的 JSON 明细 |
| `OBJ_IMPORT_BATCH_RESULT=` | 整批导入完成，含批次目录、母材质与文件数 |
| `OBJ_IMPORT_ERROR=` | 导入脚本报错，失败信息会被提取成最终错误 |
| `OBJ_IMPORT_UNLOAD_SKIPPED=` | 导入阶段有资产没能卸载（仍被引用），只影响内存占用，不影响导入结果 |
| `[TexturePropertyBatch]` | 改纹理阶段的日志前缀 |
| `[BuildLevel]` | 建关卡阶段的日志前缀 |
| `OBJ_IMPORT_LEVEL=` | 关卡生成完成，含关卡路径、模型数、`placement_mode`、对齐方式、大纲目录、偏移量与总包围盒 |
| `OBJ_LEVEL_ERROR=` | 建关卡脚本报错，失败信息会被提取成最终错误 |

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
- 母材质副本、关卡 `mapObjImport_<时间戳>.umap` 与 `metadata.json` 都在批次目录的 `DasDataInfo\` 里，程序不会清理历史批次。副本被批次资产引用，删之前先确认对应批次已经不需要了；确认后删掉批次目录 `<时间戳>\` 即可。`metadata.json` 不是 `.uasset`，在内容浏览器里删批次目录不会带走它，从资源管理器删整个目录才干净。`Content\DasMaterial` 只放工具自带的模板资产，每次运行会被覆盖复制，不要往里面加东西。
- 建关卡阶段会一次性加载整批 StaticMesh（连带材质实例与纹理头），这是全流程的内存峰值。瓦块特别多时用 `--skip-level` 跳过，之后单独处理。
- 「取消」会先 `terminate` 再 `kill` 编辑器进程；此时已经写入项目的资产不会回滚。
