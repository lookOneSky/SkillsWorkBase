---
name: das-ue-import-obj
description: 用户要求把 OBJ 或倾斜模型导入 Unreal Engine 项目，或提供 OBJ 目录与 `.uproject` 时使用。
user-invocable: false
---

# Unreal OBJ 导入

在 Windows 上用 Skill 自带的 `obj_ue_import.exe` 把 OBJ 目录批量导入 Unreal 项目，批量修改导入纹理属性并生成汇总关卡。

1. 获取 OBJ 目录（也可以是单个 `.obj`）和目标 `.uproject`，缺少任一项先询问，不要猜测路径。UE 参考原点是可选项；用户要配置时，必须同时获取经度、纬度和高程，不要猜测缺失值。
2. 运行前确认目标项目没有被 Unreal 编辑器打开，否则导入必定失败。
3. 执行程序是 Skill 自带的 `<本 Skill 目录>\ObjUeImport\obj_ue_import.exe`，不要另找路径。
4. 在 PowerShell 里必须接管道输出，否则不会等待程序退出：

   ```powershell
   & "<本 Skill 目录>\ObjUeImport\obj_ue_import.exe" --ue-import "<OBJ目录>" "<项目.uproject>" --ue-origin "<经度,纬度,高程>" | Tee-Object -FilePath "<日志路径>"
   ```

   不配置参考原点时删掉整个 `--ue-origin` 选项。顺序必须是经度、纬度、高程；经纬度单位为度，高程单位为米，经度范围 `[-180,180]`，纬度范围 `[-90,90]`，三项都必须是有限数值。
5. 判读结果：退出码 `0` 成功、`1` 执行失败、`2` 参数非法；日志里 `OBJ_IMPORT_BATCH_RESULT=` 是整批导入结果，`OBJ_IMPORT_ERROR=` 是导入报错，`[TexturePropertyBatch]` 是改纹理阶段，`OBJ_IMPORT_LEVEL=` 是汇总关卡结果，`OBJ_LEVEL_ERROR=` 是建关卡报错。指定参考原点后，只有 `OBJ_IMPORT_LEVEL=` 中的 `placement_mode` 为 `metadata_origin` 才表示原点偏移已应用；缺少 `metadata.xml` 或换算失败时导入会继续，并退回 `origin_alignment`。
6. 报告本次批次目录（默认 `/Game/ObjImport/<YYYYMMDD_HHMMSS>`）、导入数量、汇总关卡（默认位于批次目录的 `DasDataInfo/mapObjImport_<YYYYMMDD_HHMMSS>`）、参考原点及实际 `placement_mode`、日志路径。失败时保留原始错误，不要改工程资产或配置重试。
