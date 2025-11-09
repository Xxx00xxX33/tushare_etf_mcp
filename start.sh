#!/bin/bash
# Smithery MCP Server Startup Script for ETF MCP

# 设置默认端口（Smithery 使用 8081）
export PORT=${PORT:-8081}

echo "========================================="
echo "ETF MCP Server Starting"
echo "========================================="
echo "PORT: $PORT"
echo "TUSHARE_TOKEN configured: $([ -n "$TUSHARE_TOKEN" ] && echo "Yes" || echo "No")"
echo "MCP endpoint: http://0.0.0.0:$PORT/mcp"
echo "Health check: http://0.0.0.0:$PORT/health"
echo "========================================="

# 启动 uvicorn
exec uvicorn main:app --host 0.0.0.0 --port $PORT --log-level info
