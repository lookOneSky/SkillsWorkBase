# 纹理属性批处理

UE 侧的 Python 脚本，按 JSON 配置批量修改某个内容目录下全部 `Texture2D` 的属性并保存。由 `obj_ue_import.exe` 在导入完成后、建关卡之前调用，也可以单独在编辑器里跑。

只改配置里列出的属性，值已经一致的资产直接跳过（不 `modify`、不保存），因此重跑不会把没变化的资产标脏。

## 配置

`modify_texture.json`：

| 字段 | 缺省 | 说明 |
| --- | --- | --- |
| `content_directory` | 必填 | Unreal 资产路径，必须以 `/` 开头，例如 `/Game/Mesh/test`；目录不存在直接报错 |
| `recursive` | `true` | 是否递归子目录 |
| `texture_properties` | 必填，至少一项 | 要写入的属性，见下 |
| `cleanup.unload_processed` | `true` | 处理过程中分批卸载已处理的纹理 |
| `cleanup.interval` | `50` | 攒多少张卸载一次，最小 `1` |

`texture_properties` 目前只支持两项，写别的字段会直接报错：

- `max_texture_size`：整数，`0`（不限制）或 2 的幂；
- `virtual_texture_streaming`：`true` / `false`。

两项都填时按 `max_texture_size` → `virtual_texture_streaming` 的固定顺序写入。

`cleanup` 整段可以省略。导入的资产带 `RF_Standalone`，常规 GC 不回收，关掉 `unload_processed` 时内存会随纹理数量线性上涨；调小 `interval` 更省内存但 GC 更频繁，4K 纹理建议 30~50。

## 使用

被 `obj_ue_import.exe` 调用时不需要手动配置：程序会在 `%TEMP%\ObjUeImport\<时间戳>\` 生成一份临时 `modify_texture.json`，`content_directory` 填成本批次的导入目录，纹理属性按命令行覆盖，配置路径经 `sys.argv` 传入。

单独运行时，在编辑器的 Python 控制台或 commandlet 里执行脚本即可：

```python
# 用脚本同目录的 modify_texture.json
exec(open(r"D:\CodeAll\ObjDivideUtils\extern\ModifyTexture\modify_texture.py", encoding="utf-8").read())
```

配置路径取 `sys.argv` 的第一个非脚本参数（`argv[0]` 是 `.py` 时会被丢弃），缺省用脚本的同名 `.json`；支持环境变量与 `~`，相对路径按脚本所在目录解析。

运行时会弹 `ScopedSlowTask` 进度条，可随时取消；取消后仍会把最后不足一批的资产卸载干净。日志统一带 `[TexturePropertyBatch]` 前缀，结尾汇总「扫描 Texture2D N 个，修改并保存 N 个，失败 N 个」。有资产处理或保存失败时抛 `RuntimeError`，`obj_ue_import.exe` 据此判定该阶段失败。

## 实现要点

- 先用 `AssetRegistry` 的 `find_asset_data` 判类型，非 `Texture2D` 的资产**不加载**，避免为了判断类型把整个目录读进内存；类解析不出来才放行，交给 `isinstance` 兜底。
- 卸载走 `EditorLoadingAndSavingUtils.unload_packages`，而不是 `collect_garbage`——后者对 `RF_Standalone` 资产无效。卸载前会把 Python 侧的引用置空，否则对象会被钉住。
- 收集与卸载放在循环的 `finally` 里：属性没变化的分支会 `continue`，放在循环体末尾的话这条路径永远攒不满一批，等于没清理。
- 必须排在建关卡之前：关卡 Actor 会一直引用网格、材质与纹理，先建关卡会让这里的分批卸载全部落空。

## 源码依据

- `EditorAssetSubsystem.cpp`：`list_assets` / `find_asset_data` / `save_loaded_asset` 的 commandlet 行为。
- `EditorLoadingAndSavingUtils.cpp`：`UnloadPackages` 先保存、再清标记、再 GC，仍被引用的包会被安全跳过。
- `PythonScriptCommandlet.cpp`：解析 `-Script=` 并执行 Python 文件。
