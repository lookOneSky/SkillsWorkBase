# image_resize.exe 命令行说明

递归遍历一个目录里的图片，把宽或高超过上限的**按 2 的幂次整除缩小**，**就地覆盖**原文件。

不带下列参数启动（例如双击）会打开图形界面；带参数则是纯命令行模式，不弹窗，便于批处理。

## 缩放怎么算

尺寸依次整除 2、4、8、16……直到宽高都不超过上限：

```text
倍数 factor：从 1 起翻倍，直到 宽/factor ≤ 上限 且 高/factor ≤ 上限
新尺寸 = (宽 / factor, 高 / factor)        整数除法
```

| 原尺寸 | 上限 | 整除倍数 | 结果 |
| --- | --- | --- | --- |
| `4096x3000` | `2048` | 2 | `2048x1500` |
| `6000x4000` | `2048` | 4 | `1500x1000` |
| `2048x2048` | `2048` | 1 | 不处理 |

得到的边长始终是原边长的整数分之一，所以配合 `obj_texture_check.exe` 分出的 `x4` / `x16` 桶正好对得上：**`x4` 桶就是「贴图边长 ×0.5」，即上限取原边长的一半**。

**就地覆盖，不可逆。** 先用 `--dry-run` 看一遍会改哪些图、改成多大。

- **JPEG**：有损格式，覆盖等于重新编码一次。Qt 的默认质量只有 75，本程序默认用 **95**，`--quality` 可调。
- **PNG**：无损，`--quality` 对它没有影响。
- 单张图读不出、写不进（例如只读文件）只记一条告警并继续，不会让整批中断；日志里最多逐条打印 50 条，完整清单看 `--report` 的 JSON。

## 用法

```powershell
image_resize.exe --resize <图片目录> [最大边长] [选项]
```

只有 `<图片目录>` 必填。`-r` 是 `--resize` 的简写。

| 位置参数 | 省略时的默认值 |
| --- | --- |
| `<图片目录>` | 必填，递归处理其下所有子目录 |
| `[最大边长]` | `4096` 像素 |

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `--ext <后缀,…>` | `jpg,jpeg,png` | 参与处理的扩展名，大小写不敏感，写 `.png` 或 `*.png` 都认 |
| `--quality <1-100>` | `95` | JPEG 重编码质量；PNG 无关 |
| `--jobs <N>` | 自动 | 并行线程数，默认按 CPU 核数选取，上限 8 |
| `--dry-run` | 关闭 | 只试算不写文件，逐张列出将要变成的尺寸 |
| `--report <json路径>` | 不写 | 输出 JSON 统计报告 |
| `--help`, `-h` | — | 打印用法 |

运行前会回显全部生效参数，省略的标注「（默认）」。

## 示例

```powershell
:: 先看看会改哪些图，不动文件
image_resize.exe --resize "D:\Tex" --dry-run

:: 把超过 2048 的图压到 2048 以内
image_resize.exe --resize "D:\Tex" 2048

:: 处理 obj_texture_check 分出来的 x4 桶，质量稍低一点
image_resize.exe --resize "D:\Out\x4" 2048 --quality 90

:: 只处理 PNG，并留一份统计
image_resize.exe --resize "D:\Tex" 1024 --ext png --report "D:\resize.json"
```

## JSON 报告字段

顶层记录本次的口径，`summary` 是汇总，`images` 只列**被缩小的**和**出告警的**图片——达标跳过的只计数，否则几万张图会把报告撑爆。

| 字段 | 说明 |
| --- | --- |
| `inputDirectory` / `maxTextureSize` / `extensions` / `jpegQuality` / `dryRun` | 本次生效的参数 |
| `summary.scanned` / `resized` / `skipped` / `warnings` | 扫描到、缩小了、达标跳过、出告警的张数 |
| `summary.bytesBefore` / `bytesAfter` | 处理前后的总字节数（试算模式下两者相等） |
| `images[].width` / `height` / `newWidth` / `newHeight` / `scaleFactor` | 原尺寸、新尺寸、整除倍数 |
| `images[].bytesBefore` / `bytesAfter` | 该文件处理前后的字节数 |
| `images[].warning` | 出问题时的原因，正常处理的图没有这个字段 |
| `warnings[]` | 全部告警的平铺清单 |

## 退出码

| 码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | 执行失败（目录不存在、目录里没有匹配的图片、报告写入失败、被取消） |
| `2` | 参数非法 |

程序是 WIN32 子系统。未重定向时会附加到调用方的控制台，日志直接可见；重定向到文件同样有效：

```powershell
image_resize.exe --resize "D:\Tex" 2048 > resize.log
```

注意 PowerShell 不会等待 WIN32 子系统程序退出，`&` 直接调用会立刻返回提示符。需要等待时重定向输出、接管道（`| Out-String`），或用 `Start-Process -Wait`。

## 图形界面

不带参数启动即打开界面，控件与命令行选项一一对应：图片目录、最大边长、JPEG 质量、「只试算，不写文件」。**「只试算」默认勾着**；取消勾选后点开始会先弹一次确认，因为那一步不可撤销。处理在后台线程进行，进度条实时走、日志滚动、随时可以取消。

## 从源码构建

Qt 6（或 Qt 5）+ CMake 3.21+ + MSVC：

```powershell
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="C:/Qt/6.11.1/msvc2022_64"
cmake --build build
```

产物在 `build/bin/image_resize.exe`。

本仓库还留着三个不参与默认构建的旧工具，需要时打开对应开关：

| CMake 选项 | 目标 | 说明 |
| --- | --- | --- |
| `IMAGE_RESIZE_BUILD_KTX` | `image_ktx.exe` | PNG 批量转 KTX2，运行时需要 PATH 里有 `toktx` |
| `IMAGE_RESIZE_BUILD_TILES` | `image_tiles.exe` | 瓦块目录整理：按清单拷贝、按纹理数筛选、删已导入 |
| `IMAGE_RESIZE_BUILD_COLMAP` | `image_colmap.exe` | COLMAP 重建流水线，需要 `colmap.exe` |
