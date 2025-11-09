# Smithery 部署修复说明

## 问题诊断

### 错误现象
```
[9:02:10 AM] HTTP POST → undefined (10003ms)
[9:02:10 AM] Request: {"method":"initialize",...}
[9:02:10 AM] HTTP error: This operation was aborted
```

### 根本原因

发现了两个关键问题：

1. **端口配置错误**
   - Dockerfile 和 smithery.yaml 硬编码端口 8000
   - Smithery 要求使用 PORT 环境变量，默认值为 8081

2. **MCP 协议响应格式错误**
   - `/mcp` 端点返回普通 JSON 响应
   - Smithery 的 Streamable HTTP 协议要求 Server-Sent Events (SSE) 格式

## 修复方案

### 1. 端口配置修复

#### 创建启动脚本 `start.sh`
```bash
#!/bin/bash
export PORT=${PORT:-8081}
echo "PORT: $PORT"
exec uvicorn main:app --host 0.0.0.0 --port $PORT --log-level info
```

#### 更新 Dockerfile
```dockerfile
# 暴露端口（Smithery 使用 8081）
EXPOSE 8081

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8081}/health || exit 1

# 启动命令
CMD ["./start.sh"]
```

#### 更新 smithery.yaml
```yaml
runtime: "container"

startCommand:
  type: "http"
  configSchema:
    type: "object"
    properties:
      TUSHARE_TOKEN:
        type: "string"
        title: "TuShare API Token"
    required: ["TUSHARE_TOKEN"]
```

移除了 `commandFunction`，因为 Smithery 会自动使用 Dockerfile 的 CMD。

### 2. MCP 协议修复

#### 添加 SSE 支持

**更新 imports**:
```python
from fastapi import FastAPI, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse
```

**修改 `/mcp` 端点**:
```python
@app.post("/mcp")
async def mcp_handler(request: Request):
    """MCP protocol handler with Server-Sent Events (SSE) transport."""
    body = await request.json()
    method = body.get("method")
    request_id = body.get("id")
    
    # ... 处理各种 method ...
    
    # 返回 SSE 格式
    async def event_generator():
        yield {
            "event": "message",
            "data": json.dumps(response_data, ensure_ascii=False)
        }
    
    return EventSourceResponse(event_generator())
```

**关键改进**:
- 使用 `EventSourceResponse` 返回 SSE 格式
- 协议版本改为 `2024-11-05`（与 FastMCP 一致）
- 响应格式：`event: message\ndata: {...}\n\n`

#### 更新依赖

**requirements.txt**:
```
fastapi>=0.95
uvicorn[standard]>=0.24
tushare>=1.3
pandas>=2.0
numpy>=1.21
sse-starlette>=1.6.0
```

## 测试结果

### 本地测试（端口 8081）

**启动服务器**:
```bash
$ PORT=8081 ./start.sh
=========================================
ETF MCP Server Starting
=========================================
PORT: 8081
TUSHARE_TOKEN configured: No
MCP endpoint: http://0.0.0.0:8081/mcp
Health check: http://0.0.0.0:8081/health
=========================================
INFO:     Uvicorn running on http://0.0.0.0:8081 (Press CTRL+C to quit)
```

**健康检查**:
```bash
$ curl http://localhost:8081/health
{
  "status": "healthy",
  "transport": "streamable-http"
}
```

**MCP 端点（SSE 格式）**:
```bash
$ curl -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'

event: message
data: {"jsonrpc": "2.0", "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "ETF MCP Server", "version": "0.1.0"}}, "id": 1}
```

✅ **所有测试通过！**

## 修改文件

### 新增文件
- `start.sh` - 启动脚本（处理 PORT 环境变量）
- `SMITHERY_FIX.md` - 本文档

### 修改文件
- `Dockerfile` - 使用 start.sh 和 PORT 变量
- `smithery.yaml` - 添加 runtime，简化配置
- `main.py` - MCP 端点返回 SSE 格式
- `requirements.txt` - 添加 sse-starlette

## 关键技术点

### Smithery 端口标准
- **默认端口**: 8081（不是 8000）
- **环境变量**: PORT
- **设置方式**: Smithery 自动设置 PORT=8081

### MCP Streamable HTTP 协议
- **端点**: `/mcp`
- **协议**: Server-Sent Events (SSE)
- **Content-Type**: `application/json`
- **Accept**: `application/json, text/event-stream`
- **响应格式**: 
  ```
  event: message
  data: {"jsonrpc":"2.0",...}
  ```

### SSE vs JSON
| 特性 | 普通 JSON | Server-Sent Events |
|------|-----------|-------------------|
| Content-Type | application/json | text/event-stream |
| 响应格式 | `{"key":"value"}` | `event: message\ndata: {...}` |
| 流式传输 | ❌ | ✅ |
| Smithery 支持 | ❌ | ✅ |

## 部署到 Smithery

### 1. 推送到 GitHub
```bash
git add .
git commit -m "fix: Add Smithery deployment support with SSE and PORT config"
git push origin main
```

### 2. 在 Smithery 重新部署
- 访问 https://smithery.ai/
- 找到 etf-mcp 项目
- 触发重新部署

### 3. 配置环境变量
```
TUSHARE_TOKEN=your_tushare_api_token
```

### 4. 验证部署
```bash
# 健康检查
curl https://your-deployment-url/health

# MCP 端点
curl -X POST https://your-deployment-url/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'
```

## 参考资源

- **Smithery 文档**: https://smithery.ai/docs
- **MCP 协议规范**: https://modelcontextprotocol.io/
- **SSE 规范**: https://html.spec.whatwg.org/multipage/server-sent-events.html
- **sse-starlette**: https://github.com/sysid/sse-starlette

## 总结

**修复的核心问题**:
1. ✅ 端口从硬编码 8000 改为使用 PORT 环境变量（默认 8081）
2. ✅ MCP 端点从普通 JSON 改为 SSE 格式响应
3. ✅ 添加启动脚本确保环境变量正确传递
4. ✅ 简化 smithery.yaml 配置
5. ✅ 所有端点在 8081 端口测试通过

现在应该能够成功通过 Smithery 扫描器验证了！🚀
