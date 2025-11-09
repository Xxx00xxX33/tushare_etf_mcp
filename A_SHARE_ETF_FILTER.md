# A股ETF过滤功能

## 功能说明

为了确保 `get_top_etfs_by_period` 工具只返回成分股为A股的ETF，添加了智能过滤功能，自动排除港股ETF和其他海外市场ETF。

## 过滤规则

### 排除条件

#### 1. 代码规则
- **513开头**: 港股ETF（如513100恒生ETF、513050中概互联）

#### 2. 名称关键词
**港股相关**:
- 港股、香港、恒生、恒指、H股、HK、港、中概

**海外市场**:
- 美股、纳斯达克、标普、NASDAQ、S&P
- 日本、欧洲、德国、法国

### 保留条件

#### A股ETF代码前缀

**上交所**:
- `510xxx` - 如510050(50ETF)、510300(沪深300ETF)
- `511xxx` - 债券ETF
- `512xxx` - 如512760(半导体ETF)
- `515xxx` - 如515030(新能源车ETF)
- `516xxx`
- `518xxx`
- `588xxx`

**深交所**:
- `150xxx`
- `159xxx` - 如159915(创业板ETF)
- `160xxx`

## 实现方式

### 核心函数

```python
def is_a_share_etf(code: str, name: str) -> bool:
    """
    判断是否为A股ETF（排除港股ETF和其他非A股ETF）
    
    Args:
        code: ETF代码
        name: ETF名称
    
    Returns:
        True if A股ETF, False otherwise
    """
    # 排除条件1: 代码以513开头的港股ETF
    if code.startswith('513'):
        return False
    
    # 排除条件2: 名称中包含港股相关关键词
    hk_keywords = ['港股', '香港', '恒生', '恒指', 'H股', 'HK', '港', '中概']
    if any(keyword in name for keyword in hk_keywords):
        return False
    
    # 排除条件3: 美股、日本、欧洲等海外市场ETF
    overseas_keywords = ['美股', '纳斯达克', '标普', 'NASDAQ', 'S&P', '日本', '欧洲', '德国', '法国']
    if any(keyword in name for keyword in overseas_keywords):
        return False
    
    # 保留条件: 上交所和深交所的主流A股ETF
    if code.startswith(('510', '511', '512', '515', '516', '518', '588', '150', '159', '160')):
        return True
    
    # 其他情况默认保留（谨慎起见）
    return True
```

### 应用位置

#### 1. `_get_day_top_etfs` 函数（AkShare）

```python
# 过滤掉港股ETF和海外ETF
df_filtered = df[df.apply(lambda row: is_a_share_etf(str(row['代码']), str(row['名称'])), axis=1)]

# 按涨跌幅降序排序
df_sorted = df_filtered.sort_values(by='涨跌幅', ascending=False)
```

#### 2. `_get_period_top_etfs` 函数（Tushare）

```python
# 过滤掉港股ETF和海外ETF
funds_filtered = funds_df[funds_df.apply(
    lambda row: is_a_share_etf(
        str(row['ts_code'])[:6],  # 取前6位代码
        str(row['name'])
    ), 
    axis=1
)]

# 限制处理数量
funds_to_process = funds_filtered.head(limit * 3)
```

## 测试结果

```
测试 is_a_share_etf 函数：
✓ 513100 恒生ETF: False (预期: False)
✓ 513050 中概互联: False (预期: False)
✓ 510050 50ETF: True (预期: True)
✓ 510300 沪深300ETF: True (预期: True)
✓ 159915 创业板ETF: True (预期: True)
✓ 512760 半导体ETF: True (预期: True)
```

## 使用示例

### 获取当日涨幅前10的A股ETF

```json
{
  "period": "day",
  "limit": 10
}
```

**效果**: 自动过滤掉513开头的港股ETF，只返回A股ETF

### 获取近一周涨幅前5的A股ETF

```json
{
  "period": "week",
  "limit": 5
}
```

**效果**: 自动过滤掉名称包含"港股"、"恒生"等关键词的ETF

## 优势

1. **自动化**: 无需手动筛选，自动过滤非A股ETF
2. **准确性**: 结合代码和名称双重验证
3. **全面性**: 覆盖港股、美股、日本、欧洲等海外市场
4. **灵活性**: 可根据需要轻松添加新的过滤规则

## 注意事项

1. **代码前缀**: 主要依赖513前缀识别港股ETF
2. **名称关键词**: 作为补充验证，防止遗漏
3. **默认策略**: 未明确识别的ETF默认保留（谨慎起见）
4. **持续更新**: 如发现新的港股或海外ETF模式，可及时添加规则

## 相关文档

- **NEW_TOOL_DOCUMENTATION.md** - 工具使用文档
- **DATE_FIELD_FIX.md** - 日期字段修复
- **PERFORMANCE_OPTIMIZATION.md** - 性能优化
- **README.md** - 项目总览
