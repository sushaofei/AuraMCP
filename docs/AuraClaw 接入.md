# AuraClaw 接入

AuraMCP 是 **标准 MCP `2026-07-28` Server**。AuraClaw Action Hands 用标准 MCP Client（Streamable HTTP `POST /mcp`、规范方法与规范 Header）连接本服务。

身份与生产接入仍是 AuraClaw 专用：`auth_strategy: workload_trusted_context`。Runtime 仍然只持有 `AURACLAW_HANDS_URL`。

## 登记

在 AuraClaw 的 `AURACLAW_MCP_EGRESS_SERVERS_JSON` 增加一条（Secret 只放 Vault `credential_ref`）：

```json
[
  {
    "server_id": "auramcp",
    "title": "AuraMCP extensions",
    "endpoint": "https://auramcp.internal/mcp",
    "protocol_revision": "2026-07-28",
    "credential_ref": "vault/auramcp#workload",
    "auth_strategy": "workload_trusted_context",
    "trust_level": "platform",
    "allowed_tool_prefixes": ["auramcp."],
    "allowed_resource_schemes": ["auramcp"],
    "allowed_prompt_prefixes": ["auramcp."],
    "status": "active",
    "enabled": true
  }
]
```

AuraMCP 侧对应：

- `AURAMCP_HANDS_WORKLOAD_TOKEN` 与 Vault 中的 workload 相同
- 生产必须 `AURAMCP_DEPLOYMENT_PROFILE=production` 且 `AURAMCP_ALLOW_INSECURE_IDENTITY=false`

Hands 用标准 MCP 方法访问（`server/discover`、`tools/list`、`tools/call`、`resources/*`、`prompts/*`），并发送 `Authorization: Bearer <workload>`、`X-CT-*` 与 `_meta.io.auraclaw/*`。AuraMCP 校验这些值，但不回调任何外部身份系统。专用身份叠在传输层，不改变 MCP params schema，也不另开私有 JSON-RPC 方法。

## 不要做的事

- 不要让 Runtime 或 AuraX 直连 AuraMCP。
- 不要为 AuraMCP 发明规范外 JSON-RPC 方法。
- 不要把 Hands 身份字段塞进 Tool arguments。
- 不要把 chaintower 业务 MCP 指到本服务。
- 不要把 AuraClaw 内核 Tool（如价格洞察）迁入本仓。
