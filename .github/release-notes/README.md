# 发布说明

一个版本一个文件，文件名就是标签名：`v0.2.0.md` 对应标签 `v0.2.0`。

发版时 `.github/workflows/release.yml` 读取这个文件，拼成 GitHub Release 的正文：

```text
## 安装                     <- 工作流自动生成，写精确版本号
pip install cakeui==0.2.0
pip install "cakeui-cli[build]==0.2.0"

<这个文件的内容>              <- 手写，正文的第一来源

## 本次贡献者                <- 工作流自动生成，没有人时不出现
@InfernalAzazel、@alice
```

没有对应文件时不会失败：正文回退到 GitHub 自动生成的说明（What's Changed /
Full Changelog），并在 Actions 里留一条 warning。

贡献者取上一个标签到本次标签之间的所有提交作者，按 GitHub 账号去重，机器人
（`*[bot]`）不算。只开 issue 或只在讨论区参与的人不会出现在这里。

## 写法

参考 `ghost-job` 仓库的既有格式，按「新特性 / 优化 / 修复 / 升级须知」分段，
每条先一句话说清改了什么，再补充细节：

```markdown
## 新特性

- **`cakeui sync`**：把 `web/src/lib/cakeui/` 刷新到当前安装的版本
  - 本地改过的 `cakeui-boot.ts` 默认保留，`--force` 才覆盖

## 升级须知

从 v0.1.0 升级：直接装新版本即可，已有的前端文件跑一次 `cakeui sync` 对齐。
```

正文里不用重复写版本号和安装命令，工作流会加。也别在 Release 页面上直接改
正文：重跑发布流程会按这个文件覆盖回去。
