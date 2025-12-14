import re

# 读取原始文件
with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修复1: 将默认limit从20降低到5
content = re.sub(r'limit: int = 20\)', r'limit: int = 5)', content)

# 修复2: 找到并修复循环，使用funds_to_process而不是funds
# 我们需要找到从"for fund in funds:"开始的行
lines = content.split('\n')
in_tool = False
tool_start = -1
tool_end = -1

for i, line in enumerate(lines):
    if 'async def tool_etf_performance' in line:
        in_tool = True
        tool_start = i
    elif in_tool and line.strip().startswith('async def ') and i > tool_start:
        # 找到了下一个函数，结束当前函数
        tool_end = i
        break
    elif line.strip() == '' and tool_end == -1:
        # 继续查找
        continue

if tool_end == -1:
    tool_end = len(lines)

# 在函数范围内查找"for fund in funds:"
for i in range(tool_start, tool_end):
    if 'for fund in funds:' in lines[i]:
        lines[i] = lines[i].replace('for fund in funds:', 'for fund in funds_to_process:')
        print(f"修复了第{i+1}行: {lines[i]}")
        break

content = '\n'.join(lines)

# 写回文件
with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("修复完成!")
