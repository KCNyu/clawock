# 2026-08-15 clawock-dsh npm 发布存档(独立文件,防并发会话踩踏)

> 背景:另一个会话并行在改 `memory/2026-08-15.md`,故本文件独立存档,不编辑该文件。

## 当前状态(截至 23:2x +0800)

| 项 | 状态 |
|---|---|
| npm 账号 | `kcnyu` 已注册(kcn 本人),已验证 |
| 包 | `clawock-dsh@0.1.0`,`dsh-plugin/` 目录,skill-only 包(`dsh.skills` 字段),`files: ["skills"]` |
| npm 占用检查 | registry 上 clawock-dsh 仍 404,**无并发发布**,未撞车 |
| 本地登录 | ✅ `npm whoami` → kcnyu |
| dry-run | ✅ 3 文件(README/package.json/skills/investment-decision/SKILL.md)共 2.6kB,tag latest |
| 正式 publish | ❌ 403:**账号开了 2FA,需 Authenticator OTP** |
| 待办 | ①kcn 提供 OTP(本地路径) 或 ②走 CI 路径(见下) |

## 本机环境坑(已摸清,命令模板)

1. `~/.npmrc` 只读(EROFS)→ token 写 `/tmp/dsh-npmrc` + `NPM_CONFIG_USERCONFIG=/tmp/dsh-npmrc`
2. npm registry 被配成**腾讯镜像**(mirrors.tencentyun.com)→ 必须 `NPM_CONFIG_REGISTRY=https://registry.npmjs.org`
3. `/root/.npm` cache 只读 → `NPM_CONFIG_CACHE=/tmp/npm-cache`
4. 注:/tmp 写入在 bash 调用间不持久,每次发布命令需在同一调用内重建 npmrc

```bash
# 发布命令模板(dsh-plugin 目录下)
printf '//registry.npmjs.org/:_authToken=<TOKEN>\n' > /tmp/dsh-npmrc
NPM_CONFIG_USERCONFIG=/tmp/dsh-npmrc NPM_CONFIG_REGISTRY=https://registry.npmjs.org \
  NPM_CONFIG_CACHE=/tmp/npm-cache npm publish
```

## ⚠️ 双路径决策(防双发)

- 另一会话曾记录"PR #581 npm-publish workflow(trusted publishing/OIDC)"已就绪;最新版 2026-08-15.md 中该记录**已消失**,措辞变为"唯一阻塞:无 npm 凭据"——两会话信息不一致,需 kcn 确认
- **若 GitHub Actions #581 路径存在并被触发 → 本地 publish 必须停手**;反之若走本地路径,只差一个 OTP
- 推荐:CI trusted publishing(OIDC 无需 token/OTP)优先于本地手动 publish

## 安全

- granular token(npm_ 开头,clawock-dsh 读写权限)曾出现在会话中,**明文不落库**(本文件不含 token)
- 发布完成后建议 kcn 在 npm 后台(Access Tokens)撤销该 token

## 下一步(等 kcn)

1. 确认走哪条路径(本地 OTP / CI #581)
2. 提供 Authenticator OTP(若走本地)
3. 发布后验证:`npm view clawock-dsh` + `dsh plugin --profile web add clawock-dsh`
