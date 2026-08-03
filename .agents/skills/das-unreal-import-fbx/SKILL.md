---
name: das-unreal-import-fbx
description: 使用脚本把静态模型 FBX 导入 Unreal 项目，用默认父材质创建材质实例并绑定 BaseColor 纹理参数；用户要求导入 FBX 或提供 FBX 路径时使用。
user-invocable: false
---

# Unreal FBX 导入

1. 获取 FBX 文件路径；未提供时再询问。
2. 在 Unreal 项目目录运行：

   ```powershell
   python "<本 Skill 目录>/import_fbx.py" "<FBX 路径>"
   ```

3. 脚本默认使用 `/Script/Engine.MaterialInstanceConstant'/DasAssetLibrary/Mesh/material/MI_Model.MI_Model'` 和 BaseColor 参数 `TEX_漫反射`，把 `Building.fbx` 导入到 `/Game/Imported/Mesh/Building/`，并将模型命名为 `SM_Building`。
4. 报告导入后的模型和材质实例路径；脚本报错时直接报告。
