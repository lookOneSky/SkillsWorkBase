# das_ue_launcher.exe 使用说明

输入一个 `.uproject`，为该项目开启 Python 远程执行，再获取它已经运行的交互式 Unreal Editor；没有实例时自动启动编辑器。程序会等待 `UnrealWindow` 主窗口就绪，然后把实例信息写入项目目录下的 `DasUESkill.json`。

缓存只保存实例，不扫描、不记录关卡或其他编辑器状态。

## 使用

双击程序打开 Qt 图形界面，只需选择一个 `.uproject` 并点击“获取 / 启动 UE”。

命令行模式：

```powershell
das_ue_launcher.exe --ue-launch "D:\Project\MyProject.uproject"
das_ue_launcher.exe --ue-launch "D:\Project\MyProject.uproject" -- -log
```

| 选项 | 说明 |
| --- | --- |
| `--skip-autoconfig` | 不改工程的 Python 远程执行配置 |
| `--restart-if-needed` | 配置有变更且已有实例时，关闭旧实例并重启使其生效 |
| `--` | 后续参数原样传给 Unreal Editor |
| `--help`, `-h` | 显示帮助 |

命令行与界面都会一直等待主窗口出现，不设置超时。界面的“停止等待”只终止本次等待，不关闭已经存在或刚启动的 UE 进程。

## Python 远程执行自动配置

`das_ue_weather.exe` 这类工具要把 Python 送进正在运行的编辑器，前提是工程开了远程执行。启动前程序会把这两处配好：

1. `Config\DefaultEngine.ini` 的 `[/Script/PythonScriptPlugin.PythonScriptPluginSettings]` 写入 `bRemoteExecution=True`；
2. `.uproject` 的 `Plugins` 里启用 `PythonScriptPlugin`。

幂等：两处都已满足时不写文件，日志输出“Python 远程执行配置已是目标状态”。改写 INI 时保留原有的编码（UTF-8 / 带 BOM 的 UTF-8 / UTF-16 / 本地编码）与换行风格；同名重复键只保留第一个。

首次开启需要改写 `.uproject`，改写后该文件的键顺序会按 JSON 规范重排、缩进统一成制表符。UE 读取 JSON 不看键顺序，功能不受影响；在编辑器里增删插件时 UE 自己也会重写这个文件。

**配置只在编辑器启动时读取。** 如果这次改了配置而该工程的编辑器已经在运行，那么当前实例仍是旧设置，结果里的 `restart_required` 会是 `true`，日志也会提示需要重启。默认**不会**自动重启：编辑器里可能有未保存的改动，直接关掉是不可逆的。确实要自动化时加 `--restart-if-needed`，程序只向主窗口发 `WM_CLOSE` 让编辑器走正常的退出流程，绝不强杀进程；等待 120 秒仍未退出（例如卡在保存确认对话框）就报错退出。

## 实例获取顺序

0. 先按上一节开启 Python 远程执行（`--skip-autoconfig` 可跳过）。
1. 读取 `<项目目录>\DasUESkill.json` 中的 `process_id`，通过 PID、进程类型和进程命令行验证实例仍然属于输入的 `.uproject`。
2. 缓存失效时查询当前 Unreal Editor 进程，完整项目路径优先；只传了 `.uproject` 文件名的进程作为回退候选。多个候选按创建时间选最新，同时则选较大 PID。
3. 没有运行实例时，根据 `.uproject` 的 `EngineAssociation` 定位引擎，选择模块可用的 Editor 配置并启动。
4. 等待 `UnrealWindow` 主窗口出现，以原子替换方式刷新实例缓存。

程序只识别交互式 `UnrealEditor*.exe`/`UE4Editor*.exe`，不会把 `UnrealEditor-Cmd.exe` 当作可复用实例。

## DasUESkill.json

```json
{
  "process_id": 1234
}
```

缓存固定生成在 `.uproject` 所在目录，**只有一个正整数 `process_id`**，不包含项目、引擎、配置、来源、时间或关卡状态等其他信息。加了自动配置之后这一点也没变。

## UE_LAUNCH_RESULT

命令行成功时最后输出单行 JSON。它是缓存的**超集**：除了 `process_id`，还带上本次运行才知道的远程执行信息，供 `das_ue_weather.exe` 直接拿来接入编辑器，省得再去解析一遍 INI。

```text
UE_LAUNCH_RESULT={"process_id":1234,"project":"D:/Project/MyProject.uproject","remote_execution":{"enabled":true,"multicast_bind_address":"127.0.0.1","multicast_group_endpoint":"239.0.0.1:6766","multicast_ttl":0,"plugin_enabled":true},"restart_required":false}
```

| 字段 | 含义 |
| --- | --- |
| `process_id` | 就绪实例的 PID，与缓存一致 |
| `project` | 规范化后的 `.uproject` 绝对路径 |
| `restart_required` | 本次改了配置但实例已在运行，需重启后才生效 |
| `remote_execution.enabled` | `bRemoteExecution` 是否为 True |
| `remote_execution.plugin_enabled` | `.uproject` 是否启用了 `PythonScriptPlugin` |
| `remote_execution.multicast_group_endpoint` | 组播组端点，缺省 `239.0.0.1:6766` |
| `remote_execution.multicast_bind_address` | 组播绑定地址，缺省 `127.0.0.1` |
| `remote_execution.multicast_ttl` | 组播 TTL，缺省 `0`（只在本机） |

## 编辑器选择

引擎根目录和 Editor 配置不接受外部输入。引擎定位顺序包括：`EngineAssociation` 相对目录、当前用户自定义构建注册表、Epic Launcher 安装记录、系统安装注册表、默认安装目录和工程所在源码树。

新启动实例优先选择模块清单、BuildId 与 DLL 均完整的 Development；否则选择最新可用的 Editor target 配置。全部候选模块都不完整时仍尝试启动，并在日志中提示问题。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 主窗口已就绪，且实例缓存写入成功 |
| `1` | 自动配置、实例查询、引擎定位、启动、等待或缓存写入失败 |
| `2` | 命令行参数错误 |

缓存写入失败不会关闭已经运行的 Unreal Editor。`restart_required` 为 `true` 时退出码仍是 `0`——实例本身是就绪的，只是远程执行还没生效，由调用方决定怎么处理。

## 发布

双击仓库根目录的 `publish_obj_tools.bat`，会把 `das_ue_launcher.exe` 与 OBJ 导入、纹理检查、经纬度换算工具一起发布到 `dist/ObjTools_YYYYMMDD/` 并生成 ZIP 包，本文档随包发布为 `README_das_ue_launcher.md`。

发布构建关掉了 FBX 转换器，不依赖 Autodesk FBX SDK；MSVC 运行库随 exe 一起发布，目标机器不需要装 VC++ 运行库，也不需要装 Python——Python 只用于在仓库里执行发布脚本。
