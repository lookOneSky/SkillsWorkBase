# Das UE 360 全景渲染

原生 C++17 / Qt Widgets 桌面程序，CMake 目标为 `das_ue_panorama`。只需选择 Level Sequence 的本地 `.uasset` 文件，程序自动向父目录查找 `.uproject`、定位 Unreal 引擎并启动或复用编辑器，即可渲染单目 360°、2:1 等距柱状图片，可继续合成带全景标识的 MP4。不需要系统 Python，内置桥接脚本由 UE 自带 Python 执行。

## 使用

1. 启动发布目录中的 `das_ue_panorama.exe`，独立发布位置为 `dist/DasUePanorama/das_ue_panorama.exe`。
2. 选择或粘贴 Level Sequence 的本地文件路径，如 `D:/Projects/MyProject/Content/SEQ/MySequence.uasset`。路径支持空格、中文和外层引号；界面保留本地路径，不再转换成 `/Game/...`。
3. 程序从序列所在目录逐级向上查找 `.uproject`，使用最近一层找到的第一个文件；同层多个文件按文件名排序取第一个。项目与引擎自动显示，无需单独选择项目。引擎定位复用主仓库 `UeEditorLocator`：项目 EngineAssociation、注册表、Epic 安装记录或项目所在引擎源码树；未注册的数字版本还可从项目历史日志定位并核对版本。
4. 输出目录默认使用项目的 `Saved/Panorama360`，可自行选择；分辨率、输出帧率也可修改，默认渲染完整序列。自定义范围按序列自身显示帧率填写，起止均包含。
5. 在 UE 编辑器打开拍摄关卡，确认子关卡、Data Layers 和可见性。点击“检查配置”可创建并校验瞬态 MRQ 配置，不渲染；若 JSON 已指定关卡，检查时不必先加载该关卡，正式渲染时要求当前关卡与配置一致。“单帧预览”以 2048×1024 渲染起始的一个序列帧，写到独立 `preview_2048` 目录。
6. 点击“开始渲染”。完成图片检查后，可自动合成 `Panorama360.mp4`。保持原序列时长，例如 30fps 序列 1140 帧，输出 60fps 时生成 2280 张图片。

默认 7680×3840、60fps、PNG、8×3 分片、每分片独立历史、空间/时间采样 2/1。只支持单目，不包含音频。输出图片每次任务从 `Panorama_000000.png` 编号，原始序列范围记录在任务清单中，不依赖参考视频。

需要启用 UE 插件：Python Editor Script Plugin、Movie Render Queue、Movie Render Queue Additional Render Passes。程序复用现有启动器自动配置 Python 远程执行；如果现有编辑器需要重启，会明确提示保存后重启，不自动关闭编辑器。渲染通道已对照 UE 5.4 本机接口；其他版本应先做单帧检查。高分辨率渲染仍取决于场景、显存和 UE 本身，程序不通过降低纹理/LOD 来省显存。

## 常用参数与高级 JSON

界面可设置序列、输出目录、分辨率、帧率、帧范围、是否合成视频，并记住上次选择；项目路径只读，随序列自动识别。高级配置留空使用内置默认值；部署包默认读取同目录 `das_ue_panorama.json`，也可选择其他 JSON。仅写需要覆盖的字段即可，未写字段继承默认值。“编辑 JSON”在未指定配置时创建用户配置后打开。

仍兼容 `/Game/SEQ/MySequence` 和 UE 的 Copy Reference。这类虚拟路径没有本地父目录，需要通过 `--project` 指定项目，或在界面使用上次已识别的项目。本地 `.uasset` 始终重新向上查找项目，不会沿用其他项目；找不到时明确报错。本地资产仍须位于识别项目的 `Content` 目录，插件资产使用 UE 引用路径。

| JSON 字段 | 用途 |
| --- | --- |
| `map_asset` | 空字符串使用当前已打开的已保存关卡；指定时要求编辑器已打开该关卡 |
| `render_preset` | 可选 MRQ 主配置资产，继承 Game Overrides、纹理与光照等；只覆盖全景通道、输出和明确设置 |
| `output` | 图片格式、前缀、编号补零、是否覆盖已有文件；默认不覆盖 |
| `panorama` | 水平/垂直分片、相机朝向、独立历史、每分片 FOV；0 表示引擎默认 |
| `quality` | 空间/时间采样、抗锯齿、引擎和渲染预热 |
| `color` / `console_variables` | 色调曲线、渲染时的数值控制台变量 |
| `video.filename` | MP4 文件名，不含目录 |
| `video.codec` / `preset` / `crf` | 默认 libx265 / medium / 18；可选 libx264 |
| `video.ffmpeg` | 留空查找 EXE 同目录、主仓库工具目录、PATH；相对路径以 JSON 所在目录为准 |
| `video.spherical_metadata` | 默认写入单目等距柱状全景元数据，播放器需支持该格式 |

玉真观可直接在“高级配置”选择部署包的 `examples/YZG.render.json`，继承原脚本的关卡与画质预设。内容如下，不修改原资产：

```json
{
  "render_preset": "/Game/SEQ/18Camer0930",
  "map_asset": "/Game/Dev_ZJY/Cesium/C_WDS/WDS_Map/YZG_Map/YZG.YZG"
}
```

EXR 仅供图片工作流，合成视频要求 PNG。MP4 合成先写独立临时文件，成功后再保存最终文件；失败保留图片。全景元数据使用 [Google Spherical Video RFC](https://github.com/google/spatial-media/blob/master/docs/spherical-video-rfc.md) 的 `moov.trak.uuid`。媒体数据偏移保持不变，因此编码阶段不启用 faststart。

“取消任务”向 UE 写入取消请求，由编辑器回调取消当前独立渲染队列；编码阶段终止 FFmpeg。已经输出的图片保留。关闭窗口会请求取消并等待，程序不会主动退出 UE。每次任务的请求、计划、状态、完成清单与 FFmpeg 日志保存在项目 `Saved/DasUePanorama/<任务编号>/`，只有 `result.json` 的 `state=complete` 才表示所选输出全部完成。不会修改原序列、渲染预设或清空编辑器已有渲染队列。

## 构建

使用已安装的 Qt 6 MSVC 2022、Visual Studio C++ 工具链、CMake 与 Ninja：

```bat
extern\DasUePanorama\build_release.bat --test
```

构建目录为 `build-ue-panorama`，部署目录为 `dist/DasUePanorama`。脚本复用主仓库的工具链定位，将 Qt 依赖和已有的 FFmpeg 一起部署。已有高级配置不会被重新构建覆盖。可通过主仓库已有的 `QT_ROOT`、`CMAKE_EXE`、`NINJA_EXE` 指定工具位置。

主仓库的 `publish_obj_tools.bat` 和 `build_release.bat` 也会显式开启全景目标，将程序、Qt 依赖、默认配置、配置示例、`examples` 与使用说明收进各自的发布目录和 ZIP；常用工具包同时执行 `--help` 自检并将完整目录镜像到已配置的 Skill 工作区。三种发布方式共用配置与 FFmpeg 收集逻辑：优先使用主仓库 `tools/video_frames_ffmpeg/ffmpeg.exe`，其次查找 PATH，并收集可用的许可文件与来源说明。未找到 FFmpeg 时保留图片渲染能力并提示配置 `video.ffmpeg`。独立 OBJ MCP 和天气 MCP 发布显式关闭全景 GUI 构建。

也可独立配置与构建该子目录，或从主仓库以 `OBJ_DIVIDER_BUILD_UE_PANORAMA=ON` 启用；需要的共享代码只来自主仓库 Qt 工具，不调用 Unreal 编译器或构建 Unreal 工程。

```powershell
cmake -S extern/DasUePanorama -B build-ue-panorama -G Ninja -DCMAKE_PREFIX_PATH=C:/Qt/6.11.1/msvc2022_64 -DCMAKE_BUILD_TYPE=Release
cmake --build build-ue-panorama
```

命令行支持 `--sequence`、`--output`、`--config` 预填界面；本地序列无需 `--project`，未指定输出目录时使用项目 `Saved/Panorama360`。`--project` 用于 `/Game/...` 和 Copy Reference。`--validate` 只检查本地参数与自动定位的引擎，不启动 UE；`--check` 连接 UE 验证实际序列与 MRQ 参数，不渲染。`--smoke-test <png>` 保存窗口截图后退出，用于部署验证，也不启动 UE。

```powershell
das_ue_panorama.exe --sequence "D:/Projects/MyProject/Content/SEQ/MySequence.uasset" --validate
```

## 验证记录

2026-10-28：21 项本地用例通过，包括引擎定位回归、帧范围换算、路径/配置校验、真实 HEVC 编码与 MP4 全景元数据写入。部署包窗口已启动并检查；根 CMake 配置通过。使用玉真观项目、目标序列及 `examples/YZG.render.json` 成功连接 UE 5.4.4，实际创建瞬态 MRQ 配置并检查通过：序列 0～1139，60fps 输出 2280 张，38 秒。未启动整段 8K 渲染，未验证正式画面内容和高分辨率显存占用。
