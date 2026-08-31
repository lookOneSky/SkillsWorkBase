---
name: das-ue-import-obj
description: 在 Windows 上用 Skill 自带的 obj_ue_import.exe 把 OBJ 目录批量导入 Unreal 项目，并批量修改导入纹理属性；用户要求导入 OBJ、批量导入倾斜模型或提供 OBJ 目录与 .uproject 时使用。
user-invocable: false
---

# Unreal OBJ 导入

1. 获取 OBJ 目录（也可以是单个 `.obj`）和目标 `.uproject`，缺少任一项先询问，不要猜测路径。
2. 运行前确认目标项目没有被 Unreal 编辑器打开，否则导入必定失败。
3. 执行程序是 Skill 自带的 `<本 Skill 目录>\ObjUeImport\obj_ue_import.exe`，不要另找路径。
4. 在 PowerShell 里必须接管道输出，否则不会等待程序退出：

   ```powershell
   & "<本 Skill 目录>\ObjUeImport\obj_ue_import.exe" --ue-import "<OBJ目录>" "<项目.uproject>" | Tee-Object -FilePath "<日志路径>"
   ```

   不要加 `2>&1`，不要用 `Start-Process` 丢掉日志。日志路径放在临时目录。
5. 判读结果：退出码 `0` 成功、`1` 执行失败、`2` 参数非法；日志里 `OBJ_IMPORT_BATCH_RESULT=` 是整批结果，`OBJ_IMPORT_ERROR=` 是导入报错，`[TexturePropertyBatch]` 是改纹理阶段。
6. 报告本次批次目录（默认 `/Game/ObjImport/<YYYYMMDD_HHMMSS>`）、导入数量和日志路径。失败时保留原始错误，不要改工程资产或配置重试。
