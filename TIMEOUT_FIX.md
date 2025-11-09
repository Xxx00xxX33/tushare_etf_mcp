# Tushare ETF MCP 超时问题修复

## 问题描述

MCP 部署成功并连接正常，但调用工具时出现超时错误：
```
MCP error -32001: Request timed out
```

## 根本原因

**异步函数中调用同步阻塞操作**

虽然工具函数定义为 `async`，但内部调用的 Tushare API 是**同步阻塞**的：
- `pro.fund_basic()` - 同步调用
- `pro.fund_nav()` - 同步调用  
- `pro.fund_portfolio()` - 同步调用

在异步函数中直接调用同步阻塞操作会导致：
1. **事件循环被阻塞** - 整个服务器无法处理其他请求
2. **MCP 客户端超时** - 等待时间超过客户端设置的超时限制
3. **响应延迟** - 即使最终返回，响应时间也过长

## 解决方案

### 1. 使用 `asyncio.to_thread()` 包装同步调用

将所有同步的 Tushare API 调用放到线程池中执行：

```python
# ❌ 错误方式 - 直接调用同步 API
async def tool_list_etfs(*, market: str = "E") -> List[dict]:
    pro = get_pro()
    df: DataFrame = pro.fund_basic(market=market)  # 阻塞事件循环！
    return df_to_dicts(df)

# ✅ 正确方式 - 使用 asyncio.to_thread()
async def tool_list_etfs(*, market: str = "E") -> dict:
    pro = get_pro()
    df: DataFrame = await asyncio.to_thread(pro.fund_basic, market=market)
    rows = df_to_dicts(df)
    return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)}]}
```

### 2. 添加超时保护

使用 `asyncio.wait_for()` 设置 30 秒超时：

```python
async def tool_list_etfs(*, market: str = "E") -> dict:
    pro = get_pro()
    try:
        df: DataFrame = await asyncio.wait_for(
            asyncio.to_thread(pro.fund_basic, market=market),
            timeout=30.0  # 30 秒超时
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="TuShare API request timed out after 30 seconds")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TuShare API error: {exc}")
    
    rows = df_to_dicts(df)
    return {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False, indent=2)}]}
```

### 3. 修改 MCP 工具返回格式

符合 MCP 协议要求的响应格式：

```python
# ❌ 错误格式
return df_to_dicts(df)  # 直接返回列表

# ✅ 正确格式
return {
    "content": [
        {
            "type": "text",
            "text": json.dumps(rows, ensure_ascii=False, indent=2)
        }
    ]
}
```

## 修复的函数

所有工具函数都已修复：

1. ✅ `tool_list_etfs()` - 列出所有 ETF
2. ✅ `tool_etf_history()` - 获取 ETF 历史数据
3. ✅ `tool_etf_holdings()` - 获取 ETF 持仓
4. ✅ `tool_etf_performance()` - 计算 ETF 表现

## 技术细节

### asyncio.to_thread() 的工作原理

```python
# 将同步函数放到默认的 ThreadPoolExecutor 中执行
result = await asyncio.to_thread(sync_function, arg1, arg2)

# 等价于
loop = asyncio.get_event_loop()
result = await loop.run_in_executor(None, sync_function, arg1, arg2)
```

**优势**：
- ✅ 不阻塞事件循环
- ✅ 支持并发处理多个请求
- ✅ 自动管理线程池
- ✅ 简洁易读

### 为什么需要超时保护

Tushare API 可能因为以下原因响应缓慢：
- 网络延迟
- API 服务器负载高
- 数据量大
- 访问频率限制

设置超时可以：
- ✅ 避免无限等待
- ✅ 及时返回错误信息
- ✅ 释放服务器资源
- ✅ 提升用户体验

## 测试验证

### 本地测试

```bash
# 1. 语法检查
python3 -m py_compile main.py

# 2. 模块导入测试
python3 -c "import main; print('✓ 模块导入成功')"

# 3. 启动服务器
PORT=8081 ./start.sh

# 4. 测试 MCP 端点
curl -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'
```

### Smithery 部署测试

部署后应该能够：
- ✅ 通过 Smithery 扫描器验证
- ✅ 成功连接 MCP 客户端
- ✅ 调用工具不再超时
- ✅ 正常获取 Tushare 数据

## 最佳实践

### 1. 异步编程规范

```python
# ✅ 正确：async 函数中使用 await
async def async_function():
    result = await async_operation()
    return result

# ✅ 正确：async 函数中包装同步操作
async def async_wrapper():
    result = await asyncio.to_thread(sync_operation)
    return result

# ❌ 错误：async 函数中直接调用同步阻塞操作
async def bad_function():
    result = sync_blocking_operation()  # 阻塞事件循环！
    return result
```

### 2. 超时设置建议

```python
# API 调用：30 秒
await asyncio.wait_for(api_call(), timeout=30.0)

# 数据库查询：10 秒
await asyncio.wait_for(db_query(), timeout=10.0)

# 文件操作：60 秒
await asyncio.wait_for(file_operation(), timeout=60.0)
```

### 3. 错误处理

```python
try:
    result = await asyncio.wait_for(
        asyncio.to_thread(sync_api_call),
        timeout=30.0
    )
except asyncio.TimeoutError:
    # 超时错误
    raise HTTPException(status_code=504, detail="Request timed out")
except Exception as exc:
    # 其他错误
    raise HTTPException(status_code=500, detail=str(exc))
```

## 总结

**核心改进**：
1. ✅ 使用 `asyncio.to_thread()` 包装所有同步 Tushare API 调用
2. ✅ 添加 30 秒超时保护
3. ✅ 修改返回格式符合 MCP 协议
4. ✅ 改进错误处理和日志

**效果**：
- ✅ 不再阻塞事件循环
- ✅ 支持并发处理请求
- ✅ 及时响应客户端
- ✅ 提供清晰的错误信息

**部署状态**：
- ✅ 代码修复完成
- ✅ 本地测试通过
- ✅ 准备推送到 GitHub
- ✅ 可以在 Smithery 重新部署
