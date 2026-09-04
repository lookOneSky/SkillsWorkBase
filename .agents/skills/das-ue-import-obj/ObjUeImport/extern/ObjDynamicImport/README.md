# OBJ 动态导入

此工具通过 `PythonScriptCommandlet` 启动无交互 Unreal Editor，将单个 OBJ 或目录内的全部 OBJ 及其引用的
MTL、纹理导入项目 Content。一次运行只创建一个时间批次目录，所有瓦块资产直接存放在该目录内。
启动 UE 前，工具会将脚本同目录的 `DasMaterial` 覆盖复制到项目 `Content/DasMaterial`。

UE 5.3 默认使用 Interchange 导入 OBJ。为了支持自定义母材质和纹理参数名，本工具显式使用同样支持 OBJ 的旧版
`FbxFactory`；JSON 中的 `obj_import_ui`、`static_mesh_import_data` 和 `texture_import_data` 会直接写入对应
UE Python 对象。

## 配置

先编辑 `import_obj.json`：

1. 将 `project_file` 改为目标项目的 `.uproject` 绝对路径。
2. `destination_root` 默认是 `/Game/ObjImport/{timestamp}`，`{timestamp}` 会在每次运行开始时替换为
   `YYYYMMDD_HHMMSS`，对应项目物理目录 `Content/ObjImport/YYYYMMDD_HHMMSS`。
3. `parent_material` 默认是复制后的 `/Game/DasMaterial/MI_Model.MI_Model`。
   `batch_parent_material.enabled` 默认 `true`，会在导入开始前把它复制成
   `<batch_parent_material.destination_root>/MI_Model_<时间戳>`（缺省 `/Game/ObjImport`，
   与批次目录、批次关卡同级同后缀，删批次时在一个目录里就能删干净），
   本批次的材质实例全部挂到这份副本上，调参不影响历史批次。改成 `false` 则所有批次共用同一个母材质。
4. `texture_import_data` 中非空的参数名必须存在于母材质。`base_emmisive_texture_name` 的 `emmisive`
   拼写来自 UE 5.3 属性名，请勿改为 `emissive`。
5. `material_search_location=DO_NOT_SEARCH` 可避免复用同名旧材质，保证按 `parent_material` 新建材质实例。
6. `require_parent_material_instances=true` 会在导入后校验每个材质槽均为母材质实例；OBJ 应提供有效的
   `.mtl`，材质贴图路径应相对于 OBJ/MTL 可访问。
7. `build_static_mesh_ddc=true` 会在每个 OBJ 导入后等待 StaticMesh 构建及 DDC 写入完成，
   再保存资产。
8. `cleanup.unload_after_import` 默认 `true`，每导入完一批就调用 `UnloadPackages` 卸载这批资产并回收内存；
   `cleanup.interval` 默认 `1`，表示攒多少个 OBJ 卸载一次。导入的资产带 `RF_Standalone`，常规 GC 不会回收，
   关掉这项时内存会随 OBJ 数量线性上涨。`import_task.save=false` 时不会卸载，避免丢掉没保存的改动。
9. 其余 `import_task`、`obj_import_ui`、`static_mesh_import_data` 和 `texture_import_data` 项均直接映射
   UE Python 属性。

OBJ/MTL 常用映射：

- `map_Kd` -> `base_diffuse_texture_name`
- `map_Bump`/`bump` -> `base_normal_texture_name`
- `map_Ke` -> `base_emmisive_texture_name`
- `map_Ks` -> `base_specular_texture_name`
- 透明贴图 -> `base_opacity_texture_name`

## 使用

使用默认配置：

```bat
import_obj.bat "D:\data\model.obj"
```

递归导入目录内的全部 OBJ，并放入同一个时间批次目录：

```bat
import_obj.bat "D:\data\tiles"
```

临时指定另一份配置：

```bat
import_obj.bat "D:\data\model.obj" "D:\config\import_obj.json"
```

默认结果：

- UE 目录：`/Game/ObjImport/YYYYMMDD_HHMMSS`
- 物理目录：`<项目>/Content/ObjImport/YYYYMMDD_HHMMSS`
- 目录内直接包含本批次全部瓦块资产，不再为每个瓦块创建子目录
- 静态模型前缀：`SM_`
- 默认材质目录：工具内 `DasMaterial` 覆盖复制到项目 `Content/DasMaterial`
- 材质：以本批次副本 `/Game/ObjImport/MI_Model_YYYYMMDD_HHMMSS` 为父级生成材质实例

首次导入后若要覆盖同名资产，将 `import_task.replace_existing` 和 `replace_existing_settings` 改为 `true`。

## 批次关卡（build_level.py）

由 `obj_ue_import.exe` 在导入与改纹理都完成后执行，配置见 `build_level.json`：

- `level_root` + `level_name_prefix` + 批次时间戳拼成关卡路径，默认 `/Game/ObjImport/mapObjImport_YYYYMMDD_HHMMSS`；
- 批次目录里的全部 StaticMesh 用**同一个**偏移量放进关卡，瓦块相对位置与 OBJ 原始坐标一致；
- `origin_alignment` 决定这个偏移量：`bottom_center`（缺省，XY 取总包围盒中心、Z 取最小值）、
  `center`（XYZ 都取中心）、`xy_center`（只平移 XY，保留原始高程）；
- `destination_path` 与 `batch_timestamp` 由工具写入临时配置，不需要手写。

必须排在改纹理之后：关卡 Actor 会一直引用网格、材质与纹理，先建关卡会让
`modify_texture.py` 的 `UnloadPackages` 全部落空。

## 源码依据

- `FbxFactory.cpp`：`UFbxFactory` 注册并支持 `.obj`，指定工厂后不会转入 Interchange。
- `FbxMainImport.cpp`：把 `texture_import_data` 的母材质和参数名写入导入选项。
- `FbxMaterialImport.cpp`：使用 `MaterialInstanceConstantFactoryNew` 创建母材质实例并绑定 OBJ/MTL 纹理，
  `InitialParent` 取自 `FbxImportOptions.BaseMaterial`，因此换母材质只需改 `base_material_name`。
- `EditorAssetSubsystem.cpp`：`DuplicateAsset` 自带 `GIsRunningUnattendedScript` 守卫，commandlet 下复制资产不会弹框。
- `LevelEditorSubsystem.cpp`：`NewLevel` = `GEditor->NewMap()` + `SaveMap`，不依赖 Slate，可在 commandlet 中使用。
- `EditorActorSubsystem.cpp`：`SpawnActorFromObject` 传 `UStaticMesh` 会经 `UActorFactoryStaticMesh` 生成 `AStaticMeshActor`。
- `FileHelpers.cpp`：`FEditorFileUtils::SaveLevel` 见 `GIsRunningUnattendedScript` 直接失败，
  新关卡只能用 `UEditorLoadingAndSavingUtils::SaveMap` 保存。
- `PythonScriptCommandlet.cpp`：解析 `-Script=` 并执行 Python 文件。
