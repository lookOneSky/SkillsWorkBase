# Metadata 经纬度工具

独立的 Qt Widgets + C++17 + PROJ 9 程序，位于 `ObjDivideUtils/extern/MetadataCoords`。只读取 `metadata.xml`，在原坐标系下计算模型原点的经纬度，保留原始基准，不做跨坐标系的基准转换。不载入 OBJ 或纹理。无参数启动界面，带路径参数运行命令行。运行不需要 .NET 或 Python。

## 使用

```powershell
# 打开界面
.\metadata_coords.exe

# 读取 XML，输出文本
.\metadata_coords.exe "E:\Data\download\obj\metadata.xml"

# 直接输入文件夹，输出 UTF-8 JSON，可重定向或由其他程序捕获
.\metadata_coords.exe "E:\Data\download\obj" --json

# 指定输出路径
.\metadata_coords.exe --input "E:\Data\download\obj" --json --output result.json

# 界面预加载文件
.\metadata_coords.exe --gui "E:\Data\download\obj"
```

界面支持粘贴路径、选择文件、拖入单个 XML 或直接包含 metadata.xml 的文件夹，以及复制经纬度和保存 TXT / JSON。

输出坐标系自动取自输入 SRS 对应的地理坐标系。例如 EPSG:4545 的投影坐标还原为 EPSG:4490（CGCS2000）经纬度，基准不变；输入已是地理坐标时保留其坐标系和本初子午线，仅统一角度单位。界面无需选择输出坐标系，命令行不再接受 `--target` 或 `--allow-ballpark`。

默认 SRSOrigin 按东、北、Z 读取；地理坐标输入按经度、纬度、Z 读取。输入数值单位遵循 SRS（例如米、英尺、度或百分度），输出经纬度统一为度。针对北、东顺序的数据，使用 `--swap-xy`。不依据数值自动猜测或交换坐标轴。

`--proj-data <目录>` 指定包含 proj.db 的目录，默认优先使用 EXE 旁的 `share/proj`。程序禁用 PROJ 网络访问。输入若附带向其他基准转换的绑定参数（例如 `+towgs84`、`+nadgrids`），只使用其中的原始坐标系，不应用这些跨基准参数，也不需要其校正格网。JSON 保留 `target_crs`、`target_name`、`ballpark` 等结果字段；成功结果的 `ballpark` 始终为 false。

退出码：0 成功；1 输入或坐标转换失败；2 参数错误；3 输出写入失败。错误仅写入标准错误，成功结果写入标准输出。Windows 图形子系统 EXE 从交互式 cmd 启动时，cmd 可能提前返回提示符；批处理可用 `start /wait`，其他程序请等待子进程退出并检查退出码。

## 范围与精度

- SRS 支持 PROJ 可识别的投影坐标系和地理坐标系，可使用 EPSG 编码、CRS WKT，以及含 `+type=crs` 的 PROJ 定义；暂不支持地心坐标。
- ENU 局部坐标格式暂不支持，明确报错；缺少定位参数的本地坐标系无法自动还原经纬度。
- 输入为复合坐标系时，仅提取水平部分并在结果中说明。输出只包含经纬度，原始 Z 单独保留，不声称完成高程转换。
- 模型原点不一定是模型中心；需要模型内某点的位置时，应先把该点的局部坐标加到 SRSOrigin。
- `accuracy_metres` 是 PROJ 操作声明的精度，未知时为 null；不包含原始数据误差。
- 不输出高德 GCJ-02 或百度 BD-09 坐标。

样例 `EPSG:4545 / 520000,2500000,0` → CGCS2000 经度 `108.19450716°`，纬度 `22.59770511°`。

## 构建

需要 Qt 5.15 / 6 Widgets、CMake 3.21+、C++17 编译器，以及带 CMake 配置与匹配 proj.db 的 PROJ 9 安装。MSVC 下 Qt 与 PROJ 的架构、运行库和配置必须一致；已有的 PROJ 静态库可直接使用，不需要打包其开发头文件或 `.lib`。

在 VS x64 开发命令行运行，修改以下 Qt 和 PROJ 路径为本机安装目录：

```bat
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="C:/Qt/6.11.1/msvc2022_64;C:/deps/proj" -DMETADATA_COORDS_PROJ_DATA_DIR=C:/deps/proj/share/proj
cmake --build build-release
ctest --test-dir build-release --output-on-failure
cmake --install build-release --prefix dist/MetadataCoords
```

测试运行时应能找到 Qt DLL 与 offscreen 平台插件，例如把 Qt 的 bin 目录加入 PATH。测试覆盖原始基准保留、绑定参数忽略、复合坐标系水平部分、角度单位、轴顺序、JSON、错误输入和界面状态。

也可在主项目 CMakeLists.txt 中追加：

```cmake
option(OBJ_DIVIDER_BUILD_METADATA_COORDS "Build the PROJ metadata coordinate tool" OFF)
if(OBJ_DIVIDER_BUILD_METADATA_COORDS)
    add_subdirectory(extern/MetadataCoords)
endif()
```

然后配置时加 `-DOBJ_DIVIDER_BUILD_METADATA_COORDS=ON`，构建 `metadata_coords` 目标即可。开关默认关闭，避免给原有工具强加 PROJ 依赖。

## 发布

运行 `build_release.bat`，通过参数传入或预先设置 `QT_ROOT`、`PROJ_ROOT`、`VCVARS64`。脚本默认在本工具目录创建 build-release 与 dist/MetadataCoords_时间戳，并生成 ZIP，也可指定其他输出目录。运行时分发完整发布文件夹；Qt DLL、platforms/qwindows.dll、proj.db 必须与 EXE 一起携带，不能只复制 EXE。发布脚本不依赖 GDAL，不包含全部全球格网，PROJ 为动态库时会收集其必要 DLL。

Qt DLL 可以与主程序同目录共享；单独分发时会增加 Qt 运行库和 PROJ 数据库的空间。最终体积以实际发布包为准。

## 参考

- [PROJ 原生 API 与坐标轴顺序](https://proj.org/en/stable/development/quickstart.html)
- [PROJ 数据库与校正格网](https://proj.org/en/stable/resource_files.html)
- C++ 使用 PROJ 官方推荐的原生 C API，并以 RAII 管理其对象生命周期；不经过 Python 封装。
