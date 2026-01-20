# 安装和测试指南

## 快速开始

### 1. 安装依赖

```bash
cd /path/to/haopubot
pip install -r requirements.txt
```

主要依赖：
- `Telethon>=1.24.0` - Telegram客户端库
- `python-telegram-bot>=13.0,<14.0` - Bot API
- `pymongo>=3.11,<4.0` - MongoDB驱动
- `python-dotenv>=0.19.0` - 环境变量管理

### 2. 配置环境变量

复制示例配置文件：
```bash
cd agent
cp .env.example .env
```

编辑 `.env` 文件，配置必要参数：
```env
# Bot基本配置
AGENT_BOT_ID=your_agent_bot_id
AGENT_BOT_TOKEN=your_bot_token_here

# 管理员ID
ADMIN_IDS=1681704945

# 账号检测配置
API_ID=2040
API_HASH=b18441a1ff607e10a989891a5462e627
BAD_ACCOUNT_GROUP_ID=-100xxxxxxxxxx

# Session文件路径
BASE_PROTOCOL_PATH=/www/haopubot/haopu-main/协议号
FALLBACK_PROTOCOL_PATH=./协议号
```

### 3. 配置代理（可选）

如需使用代理进行账号检测：

```bash
cd agent
cp proxy.txt.example proxy.txt
```

编辑 `proxy.txt` 添加代理服务器（每行一个）：
```txt
socks5://127.0.0.1:1080
socks5://user:pass@proxy.example.com:1080
http://127.0.0.1:8080
```

### 4. 测试安装

运行测试脚本验证安装：
```bash
cd agent
python3 test_detection.py
```

预期输出：
```
🎉 所有测试通过！
```

### 5. 启动Bot

```bash
cd agent
python3 agent.py
```

## 功能说明

账号检测功能会在用户购买**协议号**类型商品时自动触发：

1. **检测流程**：
   - 通过代理连接Telegram
   - 登录账户验证Session
   - 访问 @SpamBot 获取账号状态
   - 多语言关键词匹配分类

2. **检测结果**：
   - ✅ 正常 → 发送给用户
   - ❌ 封禁 → 退款 + 发到坏号群
   - ⚠️ 冻结 → 退款 + 发到坏号群
   - ❓ 未知错误 → 发送给用户（不退款）

3. **实时进度**：
   用户会看到检测进度实时更新

4. **自动退款**：
   坏号（封禁/冻结）自动退款到用户余额

## 禁用检测

如需禁用账号检测功能，在 `.env` 中设置：
```env
ENABLE_ACCOUNT_DETECTION=false
```

或者删除/注释掉 `API_ID` 和 `API_HASH` 配置。

## 故障排查

### 问题1：ModuleNotFoundError: No module named 'telethon'

**解决**：安装依赖
```bash
pip install Telethon
```

### 问题2：检测功能未生效

**检查**：
1. 确认 `.env` 中 `ENABLE_ACCOUNT_DETECTION=true`
2. 确认配置了 `API_ID` 和 `API_HASH`
3. 查看日志：`logs/agent_bot.log`

### 问题3：代理连接失败

**检查**：
1. 确认 `proxy.txt` 格式正确
2. 确认代理服务器可用
3. 系统会自动尝试所有代理，最后回退到直连

### 问题4：Session文件找不到

**检查**：
1. 确认 `BASE_PROTOCOL_PATH` 配置正确
2. 确认目录结构：`{BASE_PROTOCOL_PATH}/{nowuid}/+86xxx.session`
3. 系统会自动尝试 `FALLBACK_PROTOCOL_PATH`

## 日志查看

查看Bot运行日志：
```bash
tail -f logs/agent_bot.log
```

检测相关日志会显示：
- 代理加载情况
- 账号检测进度
- 检测结果统计
- 退款处理记录

## 更多信息

详细功能说明请参考：[AFTER_SALES_DETECTION.md](AFTER_SALES_DETECTION.md)
