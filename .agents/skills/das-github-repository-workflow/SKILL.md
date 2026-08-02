---
name: das-github-repository-workflow
description: 使用可配置的 GitHub 账号完成仓库首次提交：把当前目录创建为私有仓库并推送到 main，或 fork 已有仓库后在指定分支提交推送。仅在仓库首次提交时使用。
user-invocable: false
---

# GitHub 仓库工作流

仅用于首次提交，提交消息固定为 `init`。

1. 直接填写同级 `github-account.json` 中的 `username`、Git 身份及认证方式。优先通过 `token_env` 引用环境变量；无法使用环境变量时才填写 `token`。
2. 创建私有仓库并推送到 `main`：

   ```bat
   create-private-repo.bat --path "仓库目录" --name "仓库名"
   ```

3. Fork 仓库并推送 JSON 中配置的分支：

   ```bat
   fork-and-push.bat OWNER/REPO --path "本地仓库目录"
   ```
