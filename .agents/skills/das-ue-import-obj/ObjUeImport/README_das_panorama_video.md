# 全景帧转 MP4

`das_panorama_video.exe` 是独立 C++17 / Qt Widgets 窗口，将 `ue-panorama` 已有的单目 2:1 全景 PNG 帧合成为带 360° 标识的 MP4。发布包自带 `ffmpeg.exe`，选择帧目录即可使用，无需指定 FFmpeg 路径，不需要运行 Unreal Editor 或系统 Python。

## 使用

1. 打开 `dist/DasPanoramaVideo/das_panorama_video.exe`。
2. 选择全景帧目录，例如 `E:/Panorama360/wudang_xyg_yxy/YXY_3-3_4-3`。
3. 点击“检查帧”：自动读取 `task_records/frames_manifest.json`，其次读取帧目录中的 `frames_manifest.json`。检查全部编号和 PNG 文件头尺寸；清单存在时必须已完成，实际帧数、首尾编号和尺寸必须匹配。允许整体移动帧目录。
4. 默认输出同目录的 `Panorama360.mp4`，也可选择其他已有目录。默认 HEVC / medium / CRF 18，保持原图尺寸；可切换 H.264、速度预设和 CRF。CRF 越小画质越高、文件越大。
5. 点击“开始渲染 MP4”。窗口显示帧数、尺寸、时长及编码进度，可取消。关闭窗口会请求取消并等待清理。

帧率留空时读取清单的 `config.output.fps_numerator/fps_denominator`，无清单时使用 60fps。可填写整数或分数，例如 `60`、`30000/1001`；修改帧率会改变视频播放时长。无清单的目录只允许一组 `前缀_000000.png`，编号必须连续且补零格式统一，支持非零起始编号。图片尺寸必须一致、宽高为偶数且宽高比为 2:1。

隐仙岩示例清单为 2584 张、7680×3840、60fps，对应 43.066667 秒。程序不缩放、不拼接、不新增中间帧，不包含音频。8K HEVC 使用软件编码，所需时间取决于硬件和速度预设；播放软件也需支持对应编码和全景标识。

输出先写同目录的唯一临时 MP4，FFmpeg 成功且完成帧数吻合后，调用现有 `SphericalMetadata` 写入单目等距柱状元数据，最后原子保存正式文件。默认不覆盖同名视频；启用覆盖时也仅在全部成功后替换。失败或取消删除本次临时视频，保留原帧与已有 MP4。同一目标的并发输出由锁文件阻止。

任务结果与 FFmpeg 日志放在输出目录的 `.das_panorama_video/<任务编号>/`；检查模式不写任务文件。只有 `result.json` 中 `state=complete` 表示输出成功。图片头检查不等于完整像素解码，编码阶段启用 FFmpeg 错误退出并再次核对完成帧数。

## 命令行

不带执行模式时打开窗口；`--validate` 只检查并输出 JSON，`--render` 直接编码后退出，两者互斥。GUI EXE 在 PowerShell 中接管道以等待结束：

```powershell
.\das_panorama_video.exe --frames "E:\Panorama360\wudang_xyg_yxy\YXY_3-3_4-3" --validate | Out-Host
.\das_panorama_video.exe --frames "E:\Panorama360\wudang_xyg_yxy\YXY_3-3_4-3" --render | Out-Host
.\das_panorama_video.exe --frames "E:\Frames" --output "E:\Videos\Tour.mp4" --fps 60 --codec libx265 --preset fast --crf 18 --render | Out-Host
```

可用 `--manifest <json>` 显式指定 UE 完成清单，`--overwrite` 允许成功后替换已有视频；`--smoke-test <png>` 保存窗口截图后退出。`--help` 查看全部参数。默认根据程序所在目录定位同级的 `ffmpeg.exe`，整个发布目录可搬迁，启动时的工作目录不影响定位。窗口不再显示 FFmpeg 路径，也不会读取以前保存的路径。命令行保留可选的 `--ffmpeg <exe>` 覆盖参数。

## 构建与复用

仓库固定的 FFmpeg 位于 `tools/ffmpeg/`，其中 `ffmpeg.exe` 使用 Git LFS 保存；首次克隆后先运行 `git lfs install` 和 `git lfs pull`。发布脚本必须收集这一版本及同目录的许可、来源说明；文件缺失或仅检出 LFS 指针时会在构建前报错。

```bat
extern\DasUePanorama\build_video_release.bat --test
```

独立视频构建目录为 `build-panorama-video`，部署目录为 `dist/DasPanoramaVideo`。入口复用原全景构建脚本的 `--video-only` 模式，只构建视频程序及所选测试，不构建 UE 工程。原 `build_release.bat` 则同时部署全景渲染和独立视频两个 EXE。独立发布、主仓库发布和直接 CMake 构建/安装都会在程序旁放置 `ffmpeg.exe`、`LICENSE_FFmpeg.txt`、`FFmpeg_SOURCE.txt`。

`PanoramaVideo` 负责帧扫描、清单校验、FFmpeg 参数和编码；`PanoramaVideoEncoder` 负责进度、取消、临时文件和最终保存。原 `PanoramaWorker::encodeVideo`、独立窗口和命令行共用这套实现；全景元数据沿用 `SphericalMetadata`，FFmpeg 定位沿用 `PanoramaConfig`，部署沿用 `collect_ffmpeg_resources`。

Qt 回归用例覆盖清单帧率、目录搬迁、缺帧、清单数量不符、尺寸错误、多组帧、覆盖保护、提前取消，以及真实 H.264 / HEVC 编码、分数帧率、中文/空格/百分号路径、帧损坏时保留原视频。真实编码用例使用 `DAS_PANORAMA_FFMPEG`，构建脚本自动设为仓库固定版本。`tests/test_panorama_ffmpeg_publish.py` 校验发布收集、缺失组件、LFS 指针和二进制校验和。

格式依据：[FFmpeg image2](https://ffmpeg.org/ffmpeg-formats.html#image2)、[FFmpeg progress](https://ffmpeg.org/ffmpeg.html)、[Google Spherical Video RFC](https://github.com/google/spatial-media/blob/master/docs/spherical-video-rfc.md)。
