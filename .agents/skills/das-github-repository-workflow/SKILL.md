---
name: das-github-repository-workflow
description: 使用可配置的 GitHub 账号完成仓库首次提交，或为 Unreal Engine 工程获取 Das 插件。用户要求创建私有仓库、首次 fork 并推送，或把 cesium-unreal、DasUnreal、DasApplication、DasPixel 克隆到 UE 工程时使用；创建与 fork 流程仅用于仓库首次提交。
user-invocable: false
---

# GitHub 仓库工作流

## 仓库首次提交

提交消息固定为 `init`。

1. 直接填写同级 `github-account.json` 中的 `username`、Git 身份及认证方式。优先通过 `token_env` 引用环境变量；无法使用环境变量时才填写 `token`。
2. 创建私有仓库并推送到 `main`：

   ```bat
   create-private-repo.bat --path "仓库目录" --name "仓库名"
   ```

3. Fork 仓库并推送 JSON 中配置的分支：

   ```bat
   fork-and-push.bat OWNER/REPO --path "本地仓库目录"
   ```

## UE 工程获取 Das 插件

1. 获取当前 UE 工程根目录：优先使用用户提供的目录；否则从当前目录逐级向上查找包含单个 `*.uproject` 的最近目录。
2. 将 UE 工程根目录显式传给同级 Python 脚本：

   ```powershell
   python "<本 Skill 目录>\clone_ue_das_plugins.py" "<UE 工程目录>"
   ```

3. 脚本将仓库递归克隆到 `<UE 工程目录>\Plugins`：
   - `lookOneSky/cesium-unreal`：`v2.15.0`
   - `lookOneSky/DasUnreal`：默认主分支
   - `lookOneSky/DasApplication`：默认主分支
   - `lookOneSky/DasPixel`：默认主分支

脚本复用 `github-account.json` 的账号、认证与代理配置。来源一致的已有插件目录会被跳过；目录冲突或已有 Cesium 检出版本不符时停止，不覆盖本地内容。
