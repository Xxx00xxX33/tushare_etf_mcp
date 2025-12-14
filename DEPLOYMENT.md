# ETF MCP Server - VPS 部署指南

本文档介绍如何在 VPS 上使用 Docker 部署 ETF MCP Server。

## 前置要求

- Docker (>= 20.10)
- Docker Compose (>= 2.0)
- TuShare API Token (从 https://tushare.pro/user/token 获取)

## 快速部署

### 1. 克隆仓库

```bash
git clone https://github.com/Xxx00xxX33/tushare_etf_mcp.git
cd tushare_etf_mcp
```

### 2. 配置环境变量

复制环境变量模板并编辑：

```bash
cp .env.example .env
nano .env  # 或使用其他编辑器
```

在 `.env` 文件中填入您的 TuShare API Token：

```
TUSHARE_TOKEN=your_actual_token_here
```

### 3. 启动服务

使用 Docker Compose 启动服务：

```bash
docker-compose up -d
```

### 4. 验证部署

检查服务状态：

```bash
# 查看容器状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 测试健康检查
curl http://localhost:8081/health
```

如果一切正常，您应该看到：

```json
{"status": "healthy"}
```

### 5. 测试 MCP 端点

```bash
curl http://localhost:8081/mcp
```

## MCP 工具说明

服务提供以下 5 个工具：

### 1. list_etfs - 搜索和列出 ETF

**功能**: 根据关键字搜索 A 股 ETF，支持按名称或代码搜索

**参数**:
- `keyword` (可选): 搜索关键字，例如 "科技"、"医药"、"510"
- `market` (可选): 市场代码，默认 "E" (ETF)
- `limit` (可选): 返回结果数量，默认 50

**示例**:
```json
{
  "keyword": "科技",
  "limit": 10
}
```

### 2. get_etf_history - 获取 ETF 历史净值

**功能**: 获取指定 ETF 的历史净值数据

**参数**:
- `ts_code` (必需): ETF 代码，例如 "510050.SH"
- `start_date` (可选): 开始日期，格式 YYYY-MM-DD 或 YYYYMMDD
- `end_date` (可选): 结束日期，格式 YYYY-MM-DD 或 YYYYMMDD
- `limit` (可选): 返回记录数，默认 100（最近的记录）

**示例**:
```json
{
  "ts_code": "510050.SH",
  "limit": 30
}
```

### 3. get_etf_holdings - 获取 ETF 持仓

**功能**: 获取指定 ETF 的成分股持仓信息

**参数**:
- `ts_code` (必需): ETF 代码，例如 "510050.SH"
- `start_date` (可选): 开始日期
- `end_date` (可选): 结束日期
- `limit` (可选): 返回持仓数量，默认 50（按权重排序）

**示例**:
```json
{
  "ts_code": "510050.SH",
  "limit": 20
}
```

### 4. get_etf_performance - 计算 ETF 区间涨幅

**功能**: 计算指定时间区间内 ETF 的涨跌幅

**参数**:
- `start_date` (必需): 开始日期
- `end_date` (必需): 结束日期
- `market` (可选): 市场代码，默认 "E"
- `limit` (可选): 处理 ETF 数量，默认 20

**示例**:
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-14",
  "limit": 10
}
```

### 5. get_top_etfs_by_period - 获取周期涨幅榜

**功能**: 获取指定周期内涨幅排行前 N 的 A 股 ETF

**参数**:
- `period` (可选): 时间周期，"week" 或 "month"，默认 "week"
- `limit` (可选): 返回数量，默认 10
- `market` (可选): 市场代码，默认 "E"

**示例**:
```json
{
  "period": "month",
  "limit": 20
}
```

## 服务管理

### 查看日志

```bash
docker-compose logs -f
```

### 重启服务

```bash
docker-compose restart
```

### 停止服务

```bash
docker-compose down
```

### 更新服务

```bash
git pull
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 端口配置

默认端口为 `8081`。如需修改，编辑 `docker-compose.yml`：

```yaml
ports:
  - "YOUR_PORT:8081"
```

## 防火墙配置

如果您的 VPS 启用了防火墙，需要开放端口：

```bash
# UFW (Ubuntu)
sudo ufw allow 8081/tcp

# firewalld (CentOS/RHEL)
sudo firewall-cmd --permanent --add-port=8081/tcp
sudo firewall-cmd --reload
```

## 反向代理配置 (可选)

### Nginx 配置示例

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8081;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 故障排查

### 容器无法启动

1. 检查 Docker 服务状态：
   ```bash
   sudo systemctl status docker
   ```

2. 查看容器日志：
   ```bash
   docker-compose logs
   ```

3. 检查端口占用：
   ```bash
   sudo netstat -tulpn | grep 8081
   ```

### API 返回错误

1. 验证 TuShare Token 是否正确：
   ```bash
   docker-compose exec etf-mcp python -c "import os; print(os.getenv('TUSHARE_TOKEN'))"
   ```

2. 测试 TuShare API 连接：
   ```bash
   docker-compose exec etf-mcp python -c "import tushare as ts; ts.set_token('YOUR_TOKEN'); pro = ts.pro_api(); print(pro.fund_basic(market='E').head())"
   ```

## 安全建议

1. **不要将 `.env` 文件提交到 Git**
   - `.env` 文件已在 `.gitignore` 中
   - 仅提交 `.env.example` 作为模板

2. **定期更新镜像**
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

3. **限制访问**
   - 使用防火墙限制访问 IP
   - 配置 Nginx 反向代理并启用 HTTPS

4. **监控日志**
   - 定期检查日志文件
   - 设置日志轮转避免磁盘占满

## 性能优化

### 调整工作进程数

编辑 `start.sh`，添加 `--workers` 参数：

```bash
exec uvicorn main:app --host 0.0.0.0 --port $PORT --workers 4 --log-level info
```

### 资源限制

在 `docker-compose.yml` 中添加资源限制：

```yaml
services:
  etf-mcp:
    # ... 其他配置 ...
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 512M
```

## 联系与支持

- GitHub Issues: https://github.com/Xxx00xxX33/tushare_etf_mcp/issues
- TuShare 文档: https://tushare.pro/document/2
