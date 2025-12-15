# ETF 搜索问题诊断

## 用户反馈的问题

以下高涨幅 ETF 无法被搜索到：

1. **卫星产业ETF (159218.SZ)** - 单周涨幅8.1%
2. **科创半导体ETF (588170.SH)** - 单日涨幅5.0%
3. **通信设备ETF** - 年内涨幅122.27%
4. **人工智能ETF** - 年内涨幅超100%

## 代码分析

### 1. `is_a_share_etf()` 函数分析

**测试用例：**

| ETF代码 | 代码前缀 | 是否匹配白名单 | 预期结果 |
|---------|----------|----------------|----------|
| 159218.SZ | 159 | ✅ 匹配（深交所159开头） | **通过** |
| 588170.SH | 588 | ✅ 匹配（上交所588开头） | **通过** |
| 515050.SH | 515 | ✅ 匹配（上交所515开头） | **通过** |
| 515070.SH | 515 | ✅ 匹配（上交所515开头） | **通过** |

**结论**：`is_a_share_etf()` 函数**不是问题所在**，所有测试 ETF 都会通过 A 股过滤。

### 2. `is_stock_etf()` 函数分析

**排除关键词列表：**
```python
['债', '债券', '货币', '理财', '黄金', '白银', '商品', 
 'REITS', 'REITs', '房地产', '可转债', '转债']
```

**测试用例：**

| ETF名称 | 是否包含排除关键词 | 预期结果 |
|---------|-------------------|----------|
| 卫星产业ETF | ❌ 不包含 | **通过** |
| 科创半导体ETF | ❌ 不包含 | **通过** |
| 通信设备ETF | ❌ 不包含 | **通过** |
| 人工智能ETF | ❌ 不包含 | **通过** |

**结论**：`is_stock_etf()` 函数**不是问题所在**，所有测试 ETF 都会通过股票型过滤。

## 可能的问题原因

### 原因 1：Tushare 数据源问题 ⭐⭐⭐⭐⭐

**最可能的原因**：

1. **权限限制**：
   - 免费 Tushare 账户可能无法获取某些 ETF 的数据
   - 科创板 ETF（588开头）可能需要更高权限
   - 新上市的 ETF 可能有延迟

2. **数据延迟**：
   - Tushare 数据可能不是实时的
   - 当日涨幅数据可能要到收盘后才更新

3. **API 返回数据不完整**：
   - `pro.fund_basic(market='E')` 可能不返回所有 ETF
   - 某些 ETF 可能被分类为其他类型

### 原因 2：搜索关键字不匹配 ⭐⭐⭐

**可能情况**：

用户搜索的关键字与 Tushare 中的实际名称不一致：

| 用户搜索 | Tushare 中的实际名称（推测） |
|----------|------------------------------|
| 卫星产业 | 可能是"卫星产业ETF"或"中证卫星产业ETF" |
| 科创半导体 | 可能是"科创板半导体ETF"或"科创50半导体ETF" |
| 通信设备 | 可能是"中证通信设备ETF"或"5G通信ETF" |
| 人工智能 | 可能是"人工智能ETF"或"AI智能ETF" |

### 原因 3：处理数量限制 ⭐⭐

**当前限制**：

在 `_get_recent_trading_days_top_etfs()` 函数中：

```python
funds_to_process = funds_filtered.head(limit * 10)  # 处理 3 * 10 = 30 个 ETF
```

如果这些高涨幅 ETF 排在第 30 名之后，就不会被处理。

**解决方案**：增加处理数量。

### 原因 4：净值数据缺失 ⭐⭐

**可能情况**：

某些 ETF 的净值数据不完整：
- 缺少最近 5 个交易日的数据
- `unit_nav` 字段为空或 NaN
- 数据被跳过（continue）

## 建议的修复方案

### 方案 1：增加调试日志 ⭐⭐⭐⭐⭐

在关键位置添加日志，帮助诊断：

```python
logger.info(f"After A-share filtering: {len(funds_filtered)} ETFs")
logger.info(f"After stock-type filtering: {len(funds_filtered)} ETFs")
logger.info(f"Processing {len(funds_to_process)} ETFs to get top {limit}")

# 记录所有计算出涨幅的 ETF
for result in results:
    logger.info(f"Calculated: {result['ts_code']} {result['name']}: {result['gain']:.2f}%")
```

### 方案 2：增加处理数量 ⭐⭐⭐⭐

```python
# 从 limit * 10 改为 limit * 50 或更多
funds_to_process = funds_filtered.head(limit * 50)  # 处理 3 * 50 = 150 个 ETF
```

### 方案 3：添加详细错误处理 ⭐⭐⭐

```python
except Exception as e:
    logger.warning(f"Error processing {fund['ts_code']} ({fund['name']}): {e}")
    # 记录更详细的错误信息
    continue
```

### 方案 4：提供完整 ETF 列表导出 ⭐⭐⭐⭐

添加一个调试工具，导出所有 A 股股票型 ETF 列表：

```python
async def tool_export_all_stock_etfs() -> dict:
    """导出所有 A 股股票型 ETF 列表（调试用）"""
    # 获取并过滤所有 ETF
    # 返回完整列表
```

## 下一步行动

1. **增加调试日志**（立即执行）
2. **增加处理数量**（立即执行）
3. **等待用户提供 Token 进行实际测试**（推荐）
4. **添加导出工具**（可选）

## 临时解决方案

如果用户急需查看这些 ETF：

1. 使用 `list_etfs` 工具搜索关键字
2. 使用 `get_etf_history` 工具手动查询特定代码
3. 使用 `get_etf_performance` 工具计算自定义时间区间的涨幅
