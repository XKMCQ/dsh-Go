# LK Store 分发（领克车机应用商店）

车机上的 dsh-go 走 **LK Store** 分发，和「把 APK 拷到 U 盘侧载」是两条不同的路径。
商店会读 APK 的真实元数据、按签名证书认包、按 `versionCode` 判新旧，所以出包时有三件事不能错。

协议原文：<https://shop.lynkco.store/api-docs/>（需要开发者账号登录）。

## 1. 硬约束

| 项 | 要求 | 错了会怎样 |
| --- | --- | --- |
| ABI | APK 的 `nativeAbis` 必须含 `x86_64` | 商店记录里 `abiParseStatus` 不通过，车机侧装不上；本仓库 `-f x64` 就是这个 |
| 包名 | `io.github.ccch1mneyyy.dsh_app` | 改包名 = 另一个应用，旧记录不会升级 |
| 签名 | 与商店记录里的 `certificateSha256` **完全一致** | 换签名后新包无法覆盖安装，必须卸载重装（本地数据丢）或新建槽位 |
| versionCode | 必须大于已上传的（本项目 = 构建分钟，单调递增） | 商店拒绝或车机判为降级 |
| 文件 | 只传 `.apk`；**不要**传 keystore / `key.properties` | 密钥泄露 |

`versionCode` 由 `tooling/build_number.py` 生成：`(年-2026)*1e8 + MMDDhhmm`（UTC+8）。
同一分钟内重复构建会撞号，跨年也是单调的，不用手工干预。

## 2. 清单适配

Android 11+ 默认看不到别的应用。要让「车机装了 LK Store」这件事可被查询到，
`AndroidManifest.xml` 里必须有（已加）：

```xml
<queries>
    <package android:name="site.lynkco.shop" />
    <provider android:authorities="site.lynkco.shop.identity" />
</queries>
```

缺这两行不会崩，但商店侧的身份读取和更新提示会静默失效——这类「装了却当没装」的 bug 很难从日志里看出来。

## 3. 通道

| 通道 | 谁能装 | 上传参数 |
| --- | --- | --- |
| `production` 正式 | 全部车机 | `testOnly=false` |
| `test` 内测 | 仅 `testVins` 白名单里的 VIN | `testOnly=true` + 至少 1 个 VIN（大写） |

测试通道**不是**正式的预热：`test` 拉不到时不允许回落到 `production`，反之正式通道也永远不会返回 test-only 的应用。
所以别把只在内测里验证过的包当成已发布。

## 4. 更新检测

公开接口，不需要车机本地 Token，适合应用自己提示更新：

```http
GET https://shop.lynkco.store/api/update/check?packageName=io.github.ccch1mneyyy.dsh_app&versionCode=<当前>&channel=production
```

客户端只认三件事同时成立：`found=true`、`published=true`、`hasUpdate=true`。
`apkUrl` 只用来**下载**；真正安装仍要走可信清单验签 + 车机本地 `127.0.0.1:39092` 的 dry-run，
不要自己拼 `pm install` 绕过校验。测试版必须显式 `channel=test`。

## 5. 上传与回读

令牌只放环境变量，**不进仓库、不进客户端、不进日志**：

```bash
export LKSTORE_TOKEN='...'

# 上传（内测槽位）
curl -s -X POST 'https://shop.lynkco.store/admin-api/lkstore/apps/upload-apk' \
  -H "Authorization: Bearer $LKSTORE_TOKEN" \
  -F 'file=@app/build/app/outputs/flutter-apk/app-x64-release.apk' \
  -F 'testOnly=true'

# 回读（必做，上传响应不算结论）
curl -s -G 'https://shop.lynkco.store/admin-api/lkstore/apps/page' \
  -H "Authorization: Bearer $LKSTORE_TOKEN" \
  --data-urlencode 'packageName=io.github.ccch1mneyyy.dsh_app' \
  --data-urlencode 'pageNo=1' --data-urlencode 'pageSize=20'
```

上传只会更新**同槽位已有记录**，不会自动建记录。`updatedExisting=true` 才算落库；
否则要用返回的 `apkUrl` 走 `apps/create` 建一条（内测必须带 `testVins`）。

回读时逐项核对：`version` / `versionCode` 与刚上传的一致、`apkSha256` 对得上、
`testOnly` 是预期的槽位、正式槽位 `status` 应为 `published`。

## 6. 红线

- 不把 Bearer Token 写进客户端代码或提交进 Git。
- 不把 `127.0.0.1:39092` 转发到局域网或公网。
- 不绕过可信清单验签，不伪造包名 / 证书摘要 / APK SHA-256 / versionCode。
- 内测通道只给白名单车机用，不当成灰度发布通道。
