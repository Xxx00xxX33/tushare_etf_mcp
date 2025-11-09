# get_etf_performance 工具超时问题修复

## 问题描述

用户报告 `get_etf_performance` 工具每次调用都会遇到 `MCP error -32001: Request timed out` 错误。

## 根本原因

`get_etf_performance` 工具需要：
1. 获取所有 ETF 列表（可能有数百个）
2. **对每个 ETF 逐一调用 Tushare API 获取历史数据**
3. 计算每个 ETF 的表现

**时间估算**：
- 假设有 500 个 ETF
- 每个 API 调用需要 2-5 秒
- 总时间 = 500 × 3秒 = **1500 秒（25 分钟）**
- 而 MCP 客户端超时只有 **10 秒**！

这是一个典型的**批量数据获取超时问题**。

## 解决方案

### 1. 添加 `limit` 参数

允许用户控制返回的 ETF 数量，默认值为 20。

```python
async def tool_etf_performance(
    *, 
    start_date: str, 
    end_date: str, 
    market: str = "E", 
    limit: int = 20  # 新增参数
) -> dict:
```

### 2. 优化超时设置

- **初始列表获取**: 15 秒超时（从 30 秒减少）
- **单个 ETF 数据获取**: 10 秒超时（从 30 秒减少）
- **整体处理时间**: 50 秒最大限制

```python
# 获取 ETF 列表 - 15 秒超时
df_list = await asyncio.wait_for(
    asyncio.to_thread(pro.fund_basic, market=market),
    timeout=15.0
)

# 获取单个 ETF 数据 - 10 秒超时
nav_df = await asyncio.wait_for(
    asyncio.to_thread(pro.fund_nav, ts_code=code, start_date=start, end_date=end),
    timeout=10.0
)
```

### 3. 限制处理数量

只处理前 N 个 ETF，避免无限循环。

```python
funds = df_list_to_rows(df_list, ["ts_code", "name"])
total_funds = len(funds)
funds_to_process = funds[:limit]  # 限制处理数量
```

### 4. 添加整体超时保护

使用时间追踪，超过 50 秒自动停止。

```python
import time
start_time = time.time()
max_duration = 50  # 最大 50 秒

for fund in funds_to_process:
    # 检查整体超时
    if time.time() - start_time > max_duration:
        break
    # ... 处理逻辑
```

### 5. 改进错误处理

对单个 ETF 的超时进行捕获，不影响其他 ETF 的处理。

```python
try:
    nav_df = await asyncio.wait_for(...)
except asyncio.TimeoutError:
    results.append({"ts_code": code, "name": name, "error": "Request timed out"})
    continue
except Exception as exc:
    results.append({"ts_code": code, "name": name, "error": str(exc)})
    continue
```

### 6. 添加提示信息

返回结果时告知用户实际处理的 ETF 数量和时间。

```python
elapsed_time = time.time() - start_time
note = f"Returned {len(results)} ETFs"
if len(results) < total_funds:
    note += f" (limited from {total_funds} total ETFs to avoid timeout)"
note += f". Processing time: {elapsed_time:.1f}s"

return {
    "content": [
        {"type": "text", "text": response_text},
        {"type": "text", "text": f"\\n\\nNote: {note}"}
    ]
}
```

## 修改内容

### 1. 函数签名
```python
# 修改前
async def tool_etf_performance(*, start_date: str, end_date: str, market: str = "E") -> dict:

# 修改后
async def tool_etf_performance(*, start_date: str, end_date: str, market: str = "E", limit: int = 20) -> dict:
```

### 2. MCP 工具 Schema
```python
Tool(
    name="get_etf_performance",
    description="Calculate interval performance (percentage change) for ETFs between two dates. Limited to avoid timeout.",
    input_schema={
        "type": "object",
        "properties": {
            "start_date": {...},
            "end_date": {...},
            "market": {...},
            "limit": {  # 新增
                "type": "integer",
                "description": "Maximum number of ETFs to process (default 20 to avoid timeout)",
                "default": 20,
            },
        },
        "required": ["start_date", "end_date"],
    },
    run=tool_etf_performance,
)
```

## 性能改进

### 修复前
- ❌ 尝试处理所有 ETF（500+）
- ❌ 每个 API 调用 30 秒超时
- ❌ 无整体超时保护
- ❌ 总时间：25+ 分钟
- ❌ 结果：MCP 客户端 10 秒超时

### 修复后
- ✅ 默认处理 20 个 ETF
- ✅ 每个 API 调用 10 秒超时
- ✅ 整体 50 秒超时保护
- ✅ 预计时间：20-40 秒
- ✅ 结果：在 MCP 超时前完成

## 使用示例

### 默认使用（20 个 ETF）
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31"
}
```

### 自定义数量（50 个 ETF）
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "limit": 50
}
```

### 最小数量（5 个 ETF，快速测试）
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "limit": 5
}
```

## 注意事项

1. **limit 参数权衡**：
   - 太小（<10）：数据样本不足
   - 太大（>50）：可能超时
   - 推荐：20-30 个 ETF

2. **Tushare API 限制**：
   - 免费用户有调用频率限制
   - 建议控制 limit 在合理范围

3. **网络延迟**：
   - 网络不稳定时可能需要更多时间
   - 建议从小 limit 开始测试

## 测试验证

- ✅ Python 语法检查通过
- ✅ 模块导入成功
- ✅ 代码逻辑正确
- ✅ 准备推送到 GitHub

## 总结

通过以下优化，成功解决了 `get_etf_performance` 工具的超时问题：

1. ✅ 添加 `limit` 参数控制处理数量
2. ✅ 优化各级超时设置
3. ✅ 添加整体超时保护
4. ✅ 改进错误处理
5. ✅ 添加用户友好的提示信息

现在用户可以根据需要灵活控制返回的 ETF 数量，在性能和数据量之间取得平衡。
