---
default_publish_method: api
default_author: "作者名"
api_proxy: "http://127.0.0.1:17881"
api_expected_egress_ip: "203.0.113.10"
need_open_comment: 1
only_fans_can_comment: 0
---

`203.0.113.10` 是示例地址，必须替换为自己的固定出口公网 IPv4，并将它加入微信公众号 API 白名单。`api_proxy` 必须指向使用者自己的代理。

把配置填写后保存到包外的 `~/.wechat-article-suite/wechat-fabu/EXTEND.md`。密钥放在包外的 `~/.wechat-article-suite/.env`，设置 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET`。

网络校验：

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-api.ts --check-network
```

该命令会校验公网出口并请求微信访问令牌，不创建草稿。若出口不一致，停止提交并检查使用者自己的代理配置。
