# 企业微信微盘 (WeDrive) Web端逆向分析记录

此文档记录了企业微信“微盘”（腾讯文档收集表所在盘）在网页端的登录与直链文件拉取流程的逆向分析结果。

## 1. 登录鉴权流程 (QR Code Auth)

企业微信微盘的网页端登录采用了长轮询（Long Polling）来等待微信扫码授权。

1. **预扫码阶段**：
   - 获取二维码密钥：`GET https://work.weixin.qq.com/wework_admin/wwqrlogin/login_qrcode` -> 获取到 `qrcode_key`。
   - 探活轮询：`GET https://work.weixin.qq.com/wework_admin/wwqrlogin/check?qrcode_key=xxx&status=QRCODE_SCAN_NEVER` -> 持续返回 `QRCODE_SCAN_NEVER` 直到用户扫码。

2. **扫码及确认阶段**：
   - 手机端扫码后，轮询接口状态更变为 `QRCODE_SCAN_ING`，此时网页提示“请在手机端确认”。
   - 手机端确认后，接口最终返回 `succ`，并携带内部验证参数重定向或发起认证请求。

3. **签发最高权限 Cookies (Token Exchange)**：
   - 认证成功后，腾讯服务器在域 `drive.weixin.qq.com` 下种入四个核心授权 Cookie。只要拥有这四个 Cookie，便等同于拥有该企业微信微盘账户的最高访问读写权限：
     - `wedrive_uin`: 企业微信下的微盘身份 ID (例：`0000000000000000`)
     - `wedrive_sid`: 核心会话 ID (例：`AUtPSABbRTMGJ3RWACRVSQAA`)
     - `wedrive_skey`: 本次授权的加解密或签名验证 Key (例：`131...|168...&bff...`)
     - `wedrive_ticket`: 临时通讯票据 (例：`131...|168...&CA...`)

## 2. API 调用与提取指北

拥有上述四个 Cookie 后，你可以脱离浏览器，在代码（如 Python `requests`）中直接构造鉴权头发起请求：

- **核心规范**：
  任何指向微盘后端的 API 请求，都**必须**在 URL 参数中明文拼接 `?sid=你的wedrive_sid`，且 HTTP Headers 中必须含有完整的上述四个 Cookie。

- **核心 API 样例**：
  - **拉取微盘首页主数据**：
    `POST https://drive.weixin.qq.com/webdisk/home?sid={wedrive_sid}`
  - **加载微盘目录空间/文件列表**：
    `POST https://drive.weixin.qq.com/diskspace/space_list?sid={wedrive_sid}`
    获取到微盘文件夹的业务元数据集及 FileID 等关键信息，返回 200 OK 且 body 为未加密的 JSON。
  - **加载具体列表数据**：
    `POST https://drive.weixin.qq.com/webdisk/list?sid={wedrive_sid}`

## 3. 分析结论与风控对抗警示

虽然 HTTP 层面的接口与鉴权已完全裸露，但**不推荐**在生产环境中手写脚本挂在云端跑自动化：

1. **时效性极其脆弱**：
   `wedrive_sid` (Session) 以及 `wedrive_ticket` 具备明确的超时和环境强相关属性，极易失效（TTL 可能仅数小时，或随微信环境刷新而失效）。
2. **底层强风控介入 (TCaptcha)**：
   在逆向过程的末尾，我们抓取到了对 `https://captcha.gtimg.com/TCaptcha.js` 的请求。这意味着微盘 API 哪怕 Cookie 全对，若频率稍高或 IP 异常，腾讯风控将强制抛给调用方一个“拖放滑块拼图（slider iframe）”的要求并阻塞 API 响应。这在纯自动化代码网络中是致命的。

> **最佳实践路径**：
> 依托桌面端的“企业微信微盘同步客户端”接管并抗住所有的 Cookie 保活与 TCaptcha 风控，仅在本地磁盘利用微盘同步下来的明文形态和 Excel 映射数据进行重组与提取。这构成了现行最高效、最稳健的全自动作业收取链路。
