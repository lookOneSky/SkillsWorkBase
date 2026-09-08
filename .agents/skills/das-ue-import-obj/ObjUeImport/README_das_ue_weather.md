# das_ue_weather.exe 使用说明

输入一个 `.uproject` 和一份时间 / 天气配置，程序会先用 `das_ue_launcher.exe` 拿到该项目正在运行的 Unreal 编辑器实例，再通过 **Python 远程执行**把设置写进 Ultra Dynamic Sky（时间）与 Ultra Dynamic Weather（天气）。

目标机器不需要装 Python：远程执行的客户端协议由本程序用 C++ 实现，编辑器里那段脚本由 UE 自带的 Python 运行。

## 使用

双击程序打开 Qt 图形界面：选 `.uproject`，填要修改的时间、选择天气类型，再点“设置时间 / 天气”。时间或天气留空时保持原样。

命令行模式：

```powershell
& "das_ue_weather.exe" --ue-weather "D:\Proj\My.uproject" --time 09:30 | Tee-Object -FilePath "$env:TEMP\weather.log"
& "das_ue_weather.exe" --ue-weather "D:\Proj\My.uproject" --weather rain --save | Tee-Object -FilePath "$env:TEMP\weather.log"
```

**外部只给类型，资产路径一律不传。** UDS / UDW 的实例和蓝图、天气预设的资产路径都由编辑器侧自己找，没有 `--sky-actor` / `--sky-blueprint` / `--weather-actor` / `--weather-blueprint` 这类选项。

> 程序是 WIN32 子系统，**PowerShell 不会等它退出**。必须接管道（`Tee-Object`）或重定向输出，否则提示符会立刻返回、日志和提示符交错。不要加 `2>&1`，不要用 `Start-Process` 丢掉日志。
>
> 打印完 `UE_WEATHER_RESULT=` 就立刻退出：本程序和它拉起的 `das_ue_launcher.exe` 都不会把标准句柄传给编辑器，Launcher 还会让新编辑器脱离可脱离的 Windows Job；管道不会挂到编辑器被关掉，Weather 正常结束、失败或取消也不会关闭已经启动的编辑器。

## 命令行选项

| 选项 | 说明 |
| --- | --- |
| `--time <HH:MM[:SS]>` | 设置 UDS 的时间，与 `--time-of-day` 互斥 |
| `--time-of-day <0-2400>` | 直接写 UDS 原始刻度 |
| `--weather <类型>` | 天气类型，写它会先清掉全部手动覆盖开关 |
| `--config <json>` | 配置文件，缺省用随程序的 `das_ue_weather.json` |
| `--outliner-folder <名字>` | 新建 Actor 的数据大纲目录，缺省 `DasWeather` |
| `--save` | 写完保存关卡与 Actor 包 |
| `--launcher <路径>` | `das_ue_launcher.exe`，缺省找本程序同目录 |
| `--skip-launch` | 已确认编辑器在跑时跳过实例获取，用默认组播设置 |
| `--timeout <秒>` | 远程节点发现超时，缺省 15 |
| `--help`, `-h` | 显示帮助 |

**命令行的设置会盖过配置文件。** 不带 `--ue-weather` 启动则打开图形界面。

## 天气类型

`--weather` 和配置里的 `weather` 只收类型，程序把它翻成预设资产名下发，路径由编辑器侧在 `UltraDynamicSky/Blueprints/Weather_Effects/Weather_Presets` 找，找不到再按资产名扫一遍资产库——工程把 UDS 装到别的目录也能用。

| 类型 | 中文名 | 预设资产 |
| --- | --- | --- |
| `clear` | 晴 | `Clear_Skies` |
| `partly-cloudy` | 少云 | `Partly_Cloudy` |
| `cloudy` | 多云 | `Cloudy` |
| `overcast` | 阴 | `Overcast` |
| `foggy` | 雾 | `Foggy` |
| `rain-light` | 小雨 | `Rain_Light` |
| `rain` | 雨 | `Rain` |
| `thunderstorm` | 雷雨 | `Rain_Thunderstorm` |
| `snow-light` | 小雪 | `Snow_Light` |
| `snow` | 雪 | `Snow` |
| `blizzard` | 暴雪 | `Snow_Blizzard` |
| `dust` | 浮尘 | `Sand_Dust_Calm` |
| `dust-storm` | 沙尘暴 | `Sand_Dust_Storm` |

三列写哪一个都认，大小写与 `-` / `_` / 空格不敏感；写了表外的名字直接报参数错（退出码 `2`），并列出可选值。

## 时间换算

UDS 的 `Time of Day` 是 `0 ~ 2400` 的**线性**刻度，不是六十进制：

```text
total = (小时 + 分钟 / 60 + 秒 / 3600) * 100
```

| 输入 | 刻度 |
| --- | --- |
| `00:00` | `0` |
| `09:30` | `950`（不是 930） |
| `15:45` | `1575` |
| `24:00` | `2400` |

小时最大 24，分和秒最大 59。

程序会顺带读回 `Animate Time of Day`、`Randomize Time Of Day`、`Use System Time` 三个开关，只读不写；其中任何一个开着都会让写进去的时间继续被覆盖，日志里会明确提示。

每次设置时间还会检查 `Simulate Real Sun`。如果它为 `false`，程序会从当前关卡数据大纲里的 StaticMesh 真实资产路径识别 `/Game/ObjImport/<实际批次名>`，读取同批次物理目录 `DasDataInfo/metadata.json` 第一条记录的 `latitude` / `longitude`，随后设置 `Latitude`、`Longitude`、`Time Zone=8.0`、`North Yaw=270.0` 并开启 `Simulate Real Sun`、`Simulate Real Moon`、`Simulate Real Stars`。如果 `Simulate Real Sun` 已为 `true`，说明用户已经配置过，程序会明确记录“已跳过”并保留整组天体设置。

当前关卡出现多个无法由关卡路径消除歧义的 ObjImport 批次、没有 ObjImport StaticMesh、缺少对应 JSON，或经纬度无效时，时间设置会失败并指出具体原因，避免把天空配置到错误位置。

## 天气预设

`weather` 会映射成上表中的 UDS 天气预设资产。写预设前，程序会把云量、雨、雪、雾、尘和风力的 `Manual Override` 开关置 `false`，让预设完整接管天气。数值天气设置仍保留为内部接口，但不通过 JSON、命令行或图形界面对外开放。

## 配置文件

`das_ue_weather.json` 随程序分发，界面和命令行读同一份。`null` 与空串都表示**不改这一项**。

```json
{
    "time": "",
    "time_of_day": null,

    "weather": "",

    "outliner_folder": "DasWeather",
    "save": false,
    "timeout_seconds": 15
}
```

`time` 与 `time_of_day` 互斥；命令行给了其中一个时，会自动清掉配置文件里的另一个，不会撞上互斥校验。`save` 只能被 `--save` 开成 `true`（没有 `--no-save`）。

旧配置中数值天气键为 `null` 时仍可正常读取；如果它们和 `weather` 一起出现，程序只使用天气类型并忽略数值。单独填数值会报“数值天气设置暂不对外开放”。

## 运行流程

1. 校验 `.uproject`，读配置并合并命令行覆盖；一项都没设就直接报参数错，不会空跑一趟远程执行。
2. 起 `das_ue_launcher.exe --ue-launch <项目>` 拿实例，它顺带把 Python 远程执行配好；从它的 `UE_LAUNCH_RESULT=` 里取组播端点与绑定地址。
   - launcher 报 `restart_required` 时本程序直接失败，提示先重启编辑器；
   - launcher 是无限等待的，界面上点“停止”只会结束这个直接子进程，不会关闭已经启动的编辑器。
3. 把载荷 `uds_remote.py` 与计划 `uds_plan.json` 写到 `%TEMP%\DasUeWeather\<时间戳>\`。
4. UDP 组播发现节点 → 按工程根目录（回退工程名）挑出属于本项目的那个 → 本地开 TCP 端口，广播 `open_connection` 等编辑器回连。
5. 发一行引导语句执行载荷；时间任务先按上述规则初始化或保留真实天体模拟，再设置 `Time of Day`，最后从返回的 `output` 里取 `UDS_REMOTE_RESULT=`。
6. 打印每一项的写入结果，输出 `UE_WEATHER_RESULT=`，清理临时目录。

演员识别不用外面传，也不写死资产路径：先按类名（去掉蓝图的 `_C` 后缀）匹配 `Ultra_Dynamic_Sky` / `Ultra_Dynamic_Weather`，再用必需属性（`Time of Day` / `Weather`）兜底，因此改过名的子蓝图也能认出来。关卡里没有实例时找蓝图生成一个并放进 `outliner_folder`：先试默认路径 `/Game/UltraDynamicSky/Blueprints/Ultra_Dynamic_Sky`（`..._Weather`），没命中再按名字扫资产库。

## 输出

成功时最后一行是单行 JSON：

```text
UE_WEATHER_RESULT={"ok":true,"tasks":[{"kind":"sky","label":"Ultra Dynamic Sky","created":[],"actor_path":"...","actor_label":"Ultra Dynamic Sky","applied":["SetTimeofDay()"],"skipped":[],"saved":[],"before":{...},"after":{...}}]}
```

每个任务都带 `before` / `after`，可以直接看出属性有没有真的改动。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 设置已写入编辑器 |
| `1` | 实例获取、节点发现、建连或编辑器侧执行失败 |
| `2` | 命令行参数错误 |

## 发布

双击仓库根目录的 `publish_obj_tools.bat`，本程序会和 `das_ue_launcher.exe`、OBJ 导入、纹理检查、经纬度换算一起发布到 `dist/ObjTools_YYYYMMDD/`，本文档随包发布为 `README_das_ue_weather.md`。

`das_ue_weather.exe`、`das_ue_launcher.exe`、`uds_remote.py`、`das_ue_weather.json` 在包里是**平铺**的，四者必须放在同一个目录：本程序默认在自己所在目录找 launcher 和载荷。整个目录可以直接拷走、改名或换盘符。

## 已知限制

- **Ultra Dynamic Sky / Weather 是付费商城资产。** 关卡里没有实例、工程里也找不到对应蓝图时，程序会明确报错提示先把它导入工程，不会静默成功。
- 天气只能选表里那几种类型；要用自制的 `UDS_Weather_Settings` 子类，得先把它加进 `UeWeatherConfig.cpp` 的天气类型表。
- 同一个工程同时开着多个编辑器实例时，节点选择会报错，要求只保留一个。
- 改完 Python 远程执行配置**必须重启编辑器**才生效；`das_ue_launcher.exe` 默认不自动重启，需要时给它加 `--restart-if-needed`。
- 只支持 Windows。
- 不自动修改日期、时区或季节；经纬度只在真实 Sun 尚未开启时从当前 ObjImport 批次初始化一次。

## 源码依据

- `Engine\Plugins\Experimental\PythonScriptPlugin\Content\Python\remote_execution.py`：协议定义。消息是不带长度前缀的 UTF-8 JSON（`version` / `magic` / `type` / `source` / `dest` / `data`）；UDP 组播发现，TCP 命令通道由客户端监听、编辑器反向连接。
- 本程序与 Python 版有两处**有意的不同**：TCP 命令端口用 0 让系统分配（Python 版写死 `6776`，两个客户端并存必冲突）；收响应时累积到 JSON 完整为止（Python 版只做一次 `recv(8192)`，命令原样回显时会被截断）。
- 组播用原生 `setsockopt`（`IP_MULTICAST_LOOP` / `IP_MULTICAST_TTL` / `IP_MULTICAST_IF` / `IP_ADD_MEMBERSHIP`），与 `remote_execution.py` 的 `_init_broadcast_socket` 逐项对应，不用 Qt 的 `joinMulticastGroup`——它在 `127.0.0.1` 上选接口的语义与 Python 不一定等价。
