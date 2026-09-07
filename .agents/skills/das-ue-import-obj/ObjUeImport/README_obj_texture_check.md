# obj_texture_check.exe 命令行说明

度量一个 OBJ 目录里每个模型的**纹理密度**，按超采样倍率分档，把贴图明显过大的模型目录整体拷到 `x4`、`x16` 桶，并输出一份 JSON 统计。

不带下列参数启动（例如双击）会打开图形界面；带参数则是纯命令行模式，不弹窗，便于批处理。

## 纹理密度怎么算

```text
纹理密度 = 引用到的贴图总像素 ÷ 三角网总面积      单位 px²/cm²
texel 密度 = √纹理密度                          单位 px/cm
网格密度 = 三角形数量 ÷ 三角网总面积          单位 tri/m²
```

- **面积**：解析 OBJ 的 `v` 与 `f`，多边形按扇形三角化，累加每个三角形的面积。长度统一换算到厘米，OBJ 坐标本身代表什么单位由 `--obj-unit` 声明（默认 `cm`）。
- **像素**：解析 OBJ 的 `mtllib`，只统计 `usemtl` 实际用到的材质；默认只算 `map_Kd`（basecolor），`--all-maps` 才纳入法线、粗糙度等通道。贴图按绝对路径去重，同一张图被多个材质或多个 OBJ 引用只计一次。贴图尺寸只读文件头，不解码像素。
- **对象**：每个 `.obj` 的直接父目录是一个模型对象，也是分类拷贝的最小单元；一个目录里的多个 OBJ 合并成一条统计。嵌套目录各自成对象，拷贝祖先时会跳过嵌套对象，不重复拷贝。

## 分档规则

**桶名就是贴图要降到的像素倍数**：`x4` 表示像素压到 1/4（边长 ×0.5），`x16` 表示压到 1/16（边长 ×0.25）。

一档降 `--level-step` 倍像素，档位就是倍率的 log 四舍五入（`.5` 向上：`3.5` 进 4，`2.5` 进 3）：

```text
档位 level = floor( log_step(倍率) + 0.5 )      倍率 = 实际密度 ÷ 目标密度
桶名 = x{step^level}                            level 0 = 达标，不拷贝
建议贴图边长缩放 = 1 / √(step^level)
```

默认步长 4，也就是「贴图边长 ×0.5」迭代一次：

| 倍率 `实际密度 ÷ 目标密度` | 档位 | 桶目录 | 建议贴图边长 |
| --- | --- | --- | --- |
| `< 2` | 0 | 不拷贝 | 保持原样 |
| `2 ≤ r < 8` | 1 | `x4` | ×0.5 |
| `8 ≤ r < 32` | 2 | `x16` | ×0.25 |
| `≥ 32` | 3 | `x64`（需 `--max-bucket 64`） | ×0.125 |

`--level-step 2` 是一半的粒度，一档只降 2 倍像素，桶多一倍：

| 倍率 | 档位 | 桶目录 | 建议贴图边长 |
| --- | --- | --- | --- |
| `< 1.41` | 0 | 不拷贝 | 保持原样 |
| `1.41 ~ 2.83` | 1 | `x2` | ×0.707 |
| `2.83 ~ 5.66` | 2 | `x4` | ×0.5 |
| `5.66 ~ 11.3` | 3 | `x8` | ×0.354 |
| `11.3 ~ 22.6` | 4 | `x16` | ×0.25 |
| `22.6 ~ 45.3` | 5 | `x32` | ×0.177 |
| `≥ 45.3` | 6 | `x64` | ×0.125 |

默认 `--max-bucket 16`：更高的档位一律压回 `x16`，JSON 里的 `rawLevel` 仍记录未截断的原始档位。两种步长都最多到 `x64`。

## 用法

```powershell
obj_texture_check.exe --texture-check <输入目录> [输出根目录] [目标密度px/cm] [选项]
```

只有 `<输入目录>` 必填，位置参数从右往左依次可省略。`--check` 是 `--texture-check` 的简写。

| 位置参数 | 省略时的默认值 |
| --- | --- |
| `<输入目录>` | 必填，递归查找其中所有 `.obj` |
| `[输出根目录]` | `<输入目录父级>\<输入目录名>_texture` |
| `[目标密度px/cm]` | `200`（1 米贴 20000 像素） |

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `--obj-unit <单位>` | `cm` | OBJ 坐标单位，可选 `mm cm dm m km in ft yd mi` |
| `--target-density <值>` | — | 直接给 `px²/cm²`，与位置参数的 `px/cm` 二选一 |
| `--level-step <2\|4>` | `4` | 一档降多少倍像素，`4` 即贴图边长 ×0.5 |
| `--max-bucket <倍数>` | `16` | 最大像素缩减倍数，必须是步长的整数次幂，最高 `64` |
| `--all-maps` | 关闭 | 统计 MTL 全部贴图通道，默认只算 `map_Kd` |
| `--no-copy` | 关闭 | 只统计出 JSON，不拷贝任何文件 |
| `--report <json路径>` | `<输出根>\texture_density.json` | 统计报告位置 |
| `--help`, `-h` | — | 打印用法 |

运行前会回显全部生效参数，省略的标注「（默认）」。

## 示例

```powershell
:: 全部用默认值：目标 200 px/cm，输出到 D:\Obj_texture
obj_texture_check.exe --texture-check "D:\Obj"

:: 指定输出目录与目标密度
obj_texture_check.exe --texture-check "D:\Obj" "D:\Out" 5.12

:: 只看数据，不动文件
obj_texture_check.exe --texture-check "D:\Obj" --no-copy

:: OBJ 坐标是米，且允许分出 x64
obj_texture_check.exe --texture-check "D:\Obj" --obj-unit m --max-bucket 64

:: 一档只降 2 倍像素，分出 x2 / x4 / x8 / x16
obj_texture_check.exe --texture-check "D:\Obj" --level-step 2 --max-bucket 16
```

## 输出结构

```text
输出根目录/
├─ x4/                     # 贴图像素压到 1/4（边长 ×0.5）
│  └─ Tile_+000_+000/      # 原样保留相对目录结构，obj+mtl+纹理整体拷贝
├─ x16/                    # 贴图像素压到 1/16（边长 ×0.25）
│  └─ Tile_+001_+002/
└─ texture_density.json
```

**重跑安全**：每次运行会先清掉这些模型在所有桶里的旧副本再拷贝，因此改目标密度后模型换桶不会留下重复数据；本次用不到的空桶目录会被删除。达标模型不拷贝。

## JSON 报告字段

顶层记录本次的口径，`summary` 是汇总，`objects` 按密度从高到低排列（最该处理的排最前）。

| 字段 | 说明 |
| --- | --- |
| `objUnit` / `lengthUnit` / `densityUnit` | 输入坐标单位、报告长度单位（恒为 `cm`）、纹理密度单位 |
| `triangleDensityUnit` | 网格密度单位，恒为 `triangles/m^2` |
| `targetDensity` / `targetTexelPerUnit` | 本次目标密度，`px²/cm²` 与 `px/cm` |
| `levelStep` / `maxLevel` / `maxBucket` | 一档降多少倍像素、档位数量、最高桶名 |
| `countAllMaps` / `copied` | 是否统计全部贴图通道、是否执行了拷贝 |
| `summary.levels` | 各档位的对象数，键是 `x1`（达标）、`x4`、`x16`… |
| `summary.overallDensity` / `overallTexelPerUnit` | 全部对象合计的密度 |
| `summary.medianTexelPerUnit` | 各对象 texel 密度的中位数，界面上可一键设为目标 |
| `summary.copiedBytes` / `warningCount` | 本次拷贝体积、告警条数 |
| `objects[].area` / `triangleCount` / `triangleDensity` / `texturePixels` | 该对象的面积（cm²）、三角形数、网格密度（tri/m²）、去重后的贴图像素 |
| `objects[].density` / `texelPerUnit` / `ratio` | 密度、texel 密度、相对目标的倍率 |
| `objects[].level` / `rawLevel` / `textureScale` / `bucket` | 归档、未截断的原始档位、建议贴图缩放、桶名 |
| `objects[].copiedTo` | 实际拷到的位置，未拷贝时为空 |
| `objects[].objFiles[]` / `textures[]` / `warnings[]` | 逐个 OBJ 的明细（含 `triangleDensity`）、引用到的贴图尺寸、该对象的告警 |

数值保留 6 位有效数字。贴图缺失、材质未定义、无法识别的图片尺寸都记进 `warnings`，不计入像素，也不会中断本次运行；日志里只打印前 50 条，其余看 JSON。

## 退出码

| 码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | 执行失败（输入目录不存在、没有 OBJ、拷贝或写报告失败、被取消） |
| `2` | 参数非法 |

程序是 WIN32 子系统。未重定向时会附加到调用方的控制台，日志直接可见；重定向到文件同样有效：

```powershell
obj_texture_check.exe --texture-check "D:\Obj" > texture.log
```

注意 PowerShell 不会等待 WIN32 子系统程序退出，`&` 直接调用会立刻返回提示符。需要等待时重定向输出、接管道（`| Out-String`），或用 `Start-Process -Wait`。

## 图形界面

不带参数启动即打开界面，七项参数与命令行一一对应（「划分档位」列出的是这次会生成的桶阶梯，换「档位步长」会跟着重排，上限尽量停在原来的像素倍数上），另有三个按钮：

- **扫描获取密度**：只统计不拷贝，结果按对象列进表格（面积、三角形、网格密度、纹理像素、纹理密度、倍率、档位、体积），并给出整体密度与中位数。点击任意表头可按对应列切换升序、降序，默认按纹理密度降序。
- **用中位数填入**：把扫描结果的密度中位数写进目标密度，作为分档基准。
- **按目标分类拷贝**：按当前目标密度分档并拷贝；扫描条件（输入目录、单位、贴图通道）没变时直接复用上一轮的度量结果，不再重读 OBJ。

改目标密度、档位步长或档位上限只会就地重新分档、刷新表格，不会重新扫描。
