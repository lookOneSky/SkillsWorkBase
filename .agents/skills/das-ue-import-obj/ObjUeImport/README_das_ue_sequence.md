# das_ue_sequence.exe：30 秒建筑日出序列

本程序是一个 Qt/CMake 工具。选择 `.uproject` 后，它会获取或启动对应 Unreal Editor，
读取当前关卡 `DasImport` 数据，生成并播放 `/Game/Cinematics/LS_Auto`。

## 固定时间线

| 时间 | 行为 |
| --- | --- |
| 0～8 秒 | 相机位于模型最高点上方、西侧，朝 `+X`；保持不动等待日出 |
| 8～14 秒 | 沿 `-X` 第一次拉远 |
| 14～24 秒 | 沿模型外侧 `+Y` 半圆绕到东侧，镜头持续正对模型 |
| 24～30 秒 | 相机处于太阳一侧，背对太阳、朝 `-X` 正对模型，再次拉远 |

相机高度严格高于 `DasImport` 合并包围盒的最高点。前段观察地平线的射线也位于
模型包围盒上方，因此模型不会遮住日出；后段不再抬镜看太阳，而是把太阳留在相机背后。

## C++ 与 Python 边界

所有业务算法均在 `src/UeSequencePlan.cpp`：

- 合并模型包围盒并选择最高 Actor；
- 计算取景距离、高度、半圆环绕位置与 LookAt 旋转；
- 固定 30fps / 900 帧时间线；
- 选择 Ultra Dynamic Sky 和主太阳；
- 根据 UDS 经纬度、时区和当天日期，用 NOAA 太阳位置近似公式计算日出时刻；
- 生成相机、UDS 时间或 Directional Light 的完整 JSON 关键帧计划。

`sunrise_sequence_remote.py` 只是 Unreal API 桥接层，只有两种操作：

1. `inspect`：原样读取 Actor 的目录、包围盒、UDS 属性与 Directional Light 描述；
2. `apply`：读取 C++ 写出的 `sequence_plan.json`，逐项创建绑定、轨道和关键帧。

`DasImport` 目录筛选也由 C++ 完成。Python 不计算包围盒合并、日出、运镜、路径或关键帧。当经纬度/时区不可用，或当天
处于极昼极夜时，C++ 固定回退到 06:00；没有 UDS 时改为驱动主 Directional Light。
UE 5.3 的 Spawnable 相机模板若无法通过函数取得组件，桥接层会从 `camera_component`
编辑器属性取回同一组件，不改变 C++ 计划或镜头算法。

## 使用

双击 `das_ue_sequence.exe`，选择项目并点击“生成日出序列”。Launcher 的实例发现、
工程配置和编辑器启动代码已经直接链接进本程序；首次开启 Python 远程执行后如提示需要
重启，请重启编辑器再运行。

命令行：

```powershell
& "das_ue_sequence.exe" --ue-sequence "D:\Proj\My.uproject" |
    Tee-Object -FilePath "$env:TEMP\ue_sequence.log"
```

可选参数：

- `--no-play`：只生成，不自动播放；
- `--skip-launch`：已确认编辑器在运行时跳过实例获取；
- `--timeout <秒>`：远程节点发现超时，默认 15 秒。

程序会覆盖 `LS_Auto` 内已有轨道和绑定。使用 UDS 时还会关闭自动时间、随机时间、
系统时间，把 `North Yaw` 设为 270°，并保存当前关卡，确保日出方向固定为世界 `+X`。
