# das_ue_asset_path.exe 使用说明

输入一个 `.uproject` 和一个资产名，输出这个资产在工程里的完整对象路径（就是编辑器里右键 “Copy Reference” 拿到的那种 `/Game/…` 路径）。**没找到就返回空路径。**

程序**不启动 Unreal**：它直接扫描工程的 Content 目录，把 `.uasset` / `.umap` 文件路径映射成 UE 对象路径。因此查询是毫秒级的，编辑器开着也能查，目标机器不需要装 Python，也不需要引擎。

## 使用

双击程序打开 Qt 图形界面：选 `.uproject`，填资产名，回车或点“查询”。命中结果列在中间，双击某一行或点“复制路径”即可复制。

命令行模式：

```powershell
& "das_ue_asset_path.exe" --ue-asset-path "D:\Proj\My.uproject" MI_Model | Tee-Object -FilePath "$env:TEMP\assetpath.log"
& "das_ue_asset_path.exe" --ue-asset-path "D:\Proj\My.uproject" MI_Model --path-only | Tee-Object -FilePath "$env:TEMP\assetpath.log"
```

> 程序是 WIN32 子系统，**PowerShell 不会等它退出**。必须接管道（`Tee-Object`）或重定向输出，否则提示符会立刻返回、日志和提示符交错。

## 命令行选项

| 选项 | 说明 |
| --- | --- |
| `--path-only` | 只打印第一个命中的对象路径，不打日志与结果 JSON；没找到就打印空行 |
| `--help`, `-h` | 显示帮助 |

不带 `--ue-asset-path` 启动则打开图形界面。

## 匹配规则

- **只按资产名匹配**，不做资产类型过滤——工具不解析 `.uasset` 内容，因此结果里没有类名。
- **资产名区分大小写**。磁盘在 Windows 上不区分，但 UE 的资产名区分，所以只差大小写的文件**不算命中**；这种情况会额外打一条“存在只差大小写的同名资产”提示，返回值仍然是空。
- 同名资产可能有多个（分布在不同目录或不同挂载点），**全部返回**。排序规则是先 `/Game` 后插件（插件之间按名字），同一个挂载点内按对象路径；`path` 取排序后的第一个。工程和插件里各有一个同名资产时，第一条就是工程自己的那个。
- `.uasset` 与 `.umap` 都算资产：关卡同样按 `/Game/Maps/M.M` 引用。
- 跳过 `__ExternalActors__` 与 `__ExternalObjects__`：UE5 的 One File Per Actor 在那里生成海量每 Actor 包，既不是要查的资产，又会拖慢扫描。

## 扫描范围

| 磁盘目录 | UE 挂载点 |
| --- | --- |
| `<项目>\Content` | `/Game` |
| `<项目>\Plugins\**\<插件>.uplugin` 的同级 `Content` | `/<插件名>` |

挂载点名字取 `.uplugin` 的**文件名**，与它所在目录名无关，这和 UE 的挂载规则一致。

引擎自带内容（`/Engine`）与引擎目录下的插件**不在范围内**——问题是“这个 Uproject 里的资产”。工程连 `Content` 目录都没有时只打一条警告，仍然按“未找到”正常返回。

## 输出

默认输出依次是：日志行、单行 JSON 的结果、**最后一行是对象路径本身**（没找到就是空行）。批处理取最后一行即可，也可以直接用 `--path-only`。

```text
项目：D:\Proj\My.uproject
资产名：MI_Model
挂载点：/Game、/Foo
命中：/Game/Das/MI_Model.MI_Model
扫描用时 812 毫秒。
找到 1 个同名资产。
UE_ASSET_PATH_RESULT={"ok":true,"found":true,"asset_name":"MI_Model","path":"/Game/Das/MI_Model.MI_Model","matches":[{"object_path":"/Game/Das/MI_Model.MI_Model","package_path":"/Game/Das/MI_Model","mount":"/Game","file":"D:\\Proj\\Content\\Das\\MI_Model.uasset"}],"mounts":["/Game","/Foo"]}
/Game/Das/MI_Model.MI_Model
```

| 字段 | 含义 |
| --- | --- |
| `ok` | 查询本身是否跑通。**未找到时它仍是 `true`** |
| `found` | 是否有命中 |
| `asset_name` | 查询用的资产名 |
| `path` | 第一个命中的对象路径；未找到时是空串 |
| `matches` | 全部命中，每条带 `object_path`、`package_path`、`mount`、`file` |
| `mounts` | 本次扫描过的挂载点 |

`--path-only` 时 stdout 只有那一行路径，出错信息走 stderr，保证脚本拿到的永远是一行。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 查询跑通，**包括没找到** |
| `1` | 扫描失败或被中断 |
| `2` | 命令行参数或 `.uproject` 非法 |

**退出码只表示查询本身有没有跑通。** 判断资产存不存在要看输出是不是空路径（或结果 JSON 的 `found`），不要用退出码。

```powershell
$path = (& "das_ue_asset_path.exe" --ue-asset-path "D:\Proj\My.uproject" MI_Model --path-only | Out-String).Trim()
if ($path) { "资产在 $path" } else { "工程里没有这个资产" }
```

## 与 FindMaterialFunctionAsset 的区别

引擎里那份 `Engine\Build\BatchFiles\FindMaterialFunctionAsset` 走的是
`UnrealEditor-Cmd.exe -run=pythonscript`，用 AssetRegistry 查，每次要冷启动一次引擎（约 1 分钟），
项目被编辑器占用时还会失败，但它能拿到资产类型（脚本里只认 `MaterialFunction`）。

本工具反过来：不启动引擎、毫秒级、编辑器开着也能查，代价是**没有类型信息**。需要按类型过滤或校验资产真的能加载时，仍然要走编辑器那条路。

## 发布

双击仓库根目录的 `publish_obj_tools.bat`，本程序会和 `obj_ue_import.exe`、`obj_texture_check.exe`、`metadata_coords.exe`、`das_ue_launcher.exe`、`das_ue_weather.exe` 一起发布到 `dist/ObjTools_YYYYMMDD/`，本文档随包发布为 `README_das_ue_asset_path.md`。

程序只依赖 Qt Widgets，没有随行脚本或数据文件，可以从发布包里单独拷走（连同 Qt 运行库）。

## 已知限制

- 只支持 Windows 上的 Unreal 工程布局。
- 不解析 `.uasset` 头，因此没有资产类型、没有依赖关系。
- 不查引擎内容，不处理 `.uproject` 里 `AdditionalPluginDirectories` 指到工程之外的插件目录。
- 每次查询都完整扫一遍 Content，不落磁盘缓存；超大工程（数十万资产）单次查询在秒级。
