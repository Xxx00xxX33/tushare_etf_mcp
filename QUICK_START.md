# ETF MCP Server - 快速开始

## 一键部署

```bash
# 1. 克隆仓库
git clone https://github.com/Xxx00xxX33/tushare_etf_mcp.git
cd tushare_etf_mcp

# 2. 配置 Token
cp .env.example .env
echo "TUSHARE_TOKEN=your_token_here" > .env

# 3. 启动服务
docker-compose up -d

# 4. 查看日志
docker-compose logs -f
```

## 验证部署

```bash
# 健康检查
curl http://localhost:8081/health

# 测试 MCP 端点
curl http://localhost:8081/mcp
```

## 工具使用示例

### 搜索科技类 ETF

```bash
curl -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "method": "tools/call",
    "params": {
      "name": "list_etfs",
      "arguments": {
        "keyword": "科技",
        "limit": 10
      }
    }
  }'
```

### 获取 ETF 历史数据

```bash
curl -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "method": "tools/call",
    "params": {
      "name": "get_etf_history",
      "arguments": {
        "ts_code": "510050.SH",
        "limit": 30
      }
    }
  }'
```

### 获取周涨幅榜

```bash
curl -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "method": "tools/call",
    "params": {
      "name": "get_top_etfs_by_period",
      "arguments": {
        "period": "week",
        "limit": 10
      }
    }
  }'
```

## 常用命令

```bash
# 查看服务状态
docker-compose ps

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 更新服务
git pull && docker-compose up -d --build

# 查看实时日志
docker-compose logs -f

# 进入容器
docker-compose exec etf-mcp bash
```

## 问题排查

### 端口被占用

```bash
# 修改 docker-compose.yml 中的端口映射
ports:
  - "YOUR_PORT:8081"
```

### Token 配置错误

```bash
# 检查环境变量
docker-compose exec etf-mcp env | grep TUSHARE_TOKEN

# 重新配置
nano .env
docker-compose restart
```

### 容器无法启动

```bash
# 查看详细日志
docker-compose logs

# 重新构建
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

## 更多信息

- 完整部署文档: [DEPLOYMENT.md](./DEPLOYMENT.md)
- 项目 README: [README.md](./README.md)
- GitHub Issues: https://github.com/Xxx00xxX33/tushare_etf_mcp/issues
