# get_top_etfs_by_period 日期字段修复

## 问题描述

用户调用 `get_top_etfs_by_period` 工具时（参数 `period="week"`, `limit=3`），返回结果为：

```
近一周涨幅前 0 的 ETF：

处理时间: 11.5 秒
注意: 仅返回 0 个 ETF（部分 ETF 数据不足或获取失败）
```

## 问题原因

代码中使用了错误的日期字段名进行排序：

```python
# ❌ 错误的字段名
nav_df_sorted = nav_df.sort_values(by='end_date')
```

根据 [Tushare fund_nav 接口文档](https://tushare.pro/document/2?doc_id=119)，正确的日期字段名应该是 `nav_date`（净值日期），而不是 `end_date`。

## 修复方案

### 修改内容

文件：`main.py`  
位置：`_get_period_top_etfs` 函数

```python
# ✅ 修复后 - 使用正确的字段名
nav_df_sorted = nav_df.sort_values(by='nav_date')
```

### Tushare fund_nav 接口字段说明

**输出参数**：

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | TS代码 |
| ann_date | str | 公告日期 |
| **nav_date** | str | **净值日期** ⭐ |
| unit_nav | float | 单位净值 |
| accum_nav | float | 累计净值 |
| accum_div | float | 累计分红 |
| net_asset | float | 资产净值 |
| total_netasset | float | 合计资产净值 |
| adj_nav | float | 复权单位净值 |

## 测试验证

修复后代码通过以下测试：

```bash
# 语法检查
✓ Python 语法正确

# 模块导入
✓ 模块导入成功
```

## 预期效果

修复后，使用 `period="week"` 参数应该能够：
1. 正确获取 ETF 列表
2. 按 `nav_date` 排序净值数据
3. 计算准确的周涨幅
4. 返回涨幅前 N 的 ETF

## 相关文件

- `main.py` - 主要修复文件
- `TIMEOUT_FIX.md` - 之前的超时问题修复文档
- `PERFORMANCE_OPTIMIZATION.md` - 性能优化文档
- `NEW_TOOL_DOCUMENTATION.md` - 工具使用文档

## 提交信息

```
fix: Correct date field name in _get_period_top_etfs function

- Change sort field from 'end_date' to 'nav_date'
- Fix issue where get_top_etfs_by_period returned 0 ETFs
- Align with Tushare fund_nav API documentation
```
