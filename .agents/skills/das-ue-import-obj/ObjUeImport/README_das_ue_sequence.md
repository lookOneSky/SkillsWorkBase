# das_ue_sequence.exe：30 秒建筑日出序列

本程序是一个 Qt/CMake 工具。选择 `.uproject` 后，它会获取或启动对应 Unreal Editor，
读取当前关卡 `DasImport` 数据，生成并播放 `/Game/Cinematics/LS_Auto`。

## 参考与固定时间线

运镜节奏与天空时间参考仓库根目录的 `WDS_Z_Start1.uasset`。
原资源为 30fps / 24000 ticks，播放终点为第 996 帧（33.2 秒），
相机主要运动在第 716 帧结束。生成器将节奏映射到 900 帧，
将最后的停留改为继续拉远；不复制参考场景的绝对坐标。

| 时间 | 行为 |
| --- | --- |
| 0～4.4 秒 | 相机位于模型西侧、最高点上方，仰角 8.4°；局部入镜，停留观看日出 |
| 4.4～8.8 秒 | 缓慢退开并开始转向，逐渐露出模型 |
| 8.8～21.57 秒 | 沿 `-Y` 一侧继续半圈环绕，逐渐转向模型中心；结束时完整入镜 |
| 21.57～30 秒 | 处于太阳一侧、朝 `-X` 正对模型，继续拉远至模型只占视口小部分 |

天空曲线保留参考中的“上升、停留、再上升、停留”：原始关键帧为
`0:550 → 146:620 → 397:620 → 528:700`。以参考 06:00 为基准，
整体平移到当天计算出的日出时刻；不固定使用参考关卡的地理位置。
生成后在 4.4～11.97 秒保持日出后的时间，15.9 秒后保持最终时间。

## 包围盒适配

- 开场视锥下沿穿过模型顶部，只显示局部，并保留天空和地平线。
- 合并 `DasImport` 包围盒后，将八角点投影到实际相机视野，按宽、高、深计算取景距离。
- 旋转结束时八角点位于画面中央 78% 范围内；最终位于中央 20% 范围内。
  比例按画面宽、高分别约束，不是面积百分比；长宽比特殊时实际占比可能更小。
- 采用参考的 15mm 焦距，明确设置 36 × 20.25mm 画幅（16:9），避免默认镜头预设改变视野。
- 相机高度始终高于合并包围盒最高点；间距与近裁剪面随尺寸调整，支持小模型和大型场景。
- 相机只写入 8 个主要关键帧，天空时间只写入 4 个关键帧，便于继续编辑。
  环绕阶段使用自动插值，最终拉远使用线性插值，确保完整入镜后稳定后退。

参考提取记录见 [reference_WDS_Z_Start1.md](reference_WDS_Z_Start1.md)。

## C++ 与 Python 边界

运镜与时间线算法位于 `src/UeSequencePlan.cpp`，日出算法由两个 EXE 共用
`src/core/SunriseCalculator.cpp`：

- 合并模型包围盒并选择最高 Actor；
- 按视野投影计算取景距离、高度、半圈环绕与朝向；
- 固定 30fps / 900 帧时间线；
- 选择 Ultra Dynamic Sky 和主太阳；
- 根据 UDS 经纬度、时区和当天日期，用共享 NOAA 太阳位置近似公式计算日出时刻；
- 生成相机、UDS 时间或 Directional Light 的完整 JSON 关键帧计划。

`sunrise_sequence_remote.py` 只是 Unreal API 桥接层，只有两种操作：

1. `inspect`：原样读取 Actor 的目录、包围盒、UDS 属性与 Directional Light 描述；
2. `apply`：读取 C++ 写出的 `sequence_plan.json`，逐项创建绑定、轨道和关键帧。

UDS 的 `Time of Day` 使用与参考一致的 Double 轨道，保留时间精度并匹配属性类型。

`DasImport` 目录筛选也由 C++ 完成。Python 不计算包围盒合并、日出、运镜、路径或关键帧。当经纬度/时区不可用，或当天
处于极昼极夜时，C++ 固定回退到 06:00；没有 UDS 时改为驱动主 Directional Light。
UE 5.3 的 Spawnable 相机模板若无法通过函数取得组件，桥接层会从 `camera_component`
编辑器属性取回同一组件，不改变 C++ 计划或镜头算法。
画幅、焦距与近裁剪面统一用 `set_editor_property` 写入 `filmback`、
`current_focal_length`、`custom_near_clipping_plane`，不依赖 UE 5.3 Python 未暴露的独立 setter 方法。

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
