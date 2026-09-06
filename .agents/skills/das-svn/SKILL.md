---
name: das-svn
description: 用户要求配置、更新或刷新 SVN ignore 时使用。
user-invocable: false
---

# SVN ignore

脚本在 SVN 工作目录查找或创建 `svnIgnore.txt`，并据此更新 `svn:ignore` 属性。运行：

```powershell
python "<本 Skill 目录>\update_svn_ignore.py" "<SVN 工作目录>"
```
