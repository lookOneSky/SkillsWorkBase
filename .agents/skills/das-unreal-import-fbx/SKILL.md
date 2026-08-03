---
name: das-unreal-import-fbx
description: 使用脚本把静态模型 FBX 导入 Unreal 项目，用指定父材质创建材质实例并绑定 BaseColor 纹理参数；用户要求导入 FBX、指定 parent/父材质或提供 FBX 路径时使用。
user-invocable: false
---

# Unreal FBX 导入

1. 获取 FBX 文件路径、父材质对象路径和 BaseColor 纹理参数名；三项均为必填，只询问尚未提供的值。父材质使用 `/Game/Materials/M_Master.M_Master` 格式。
2. 在 Unreal 项目目录运行：

   ```powershell
   python "<本 Skill 目录>/import_fbx.py" "<FBX 路径>" "<父材质对象路径>" "<BaseColor 参数名>"
   ```

3. 脚本默认把 `Building.fbx` 导入到 `/Game/Imported/Mesh/Building/`，并将模型命名为 `SM_Building`。
4. 报告导入后的模型和材质实例路径；脚本报错时直接报告。
