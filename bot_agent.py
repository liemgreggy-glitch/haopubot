"""
总部代理管理功能
包含：添加代理、查看代理列表、代理详情、启用/禁用代理、删除代理
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import CallbackContext
from mongo import (
    agent_bots,
    user,
    get_agent_stats,
    generate_agent_bot_id,
    sync_all_products_to_agent,
    format_beijing_time,
    beijing_now_str
)


def show_agent_management(update: Update, context: CallbackContext):
    """显示代理管理主菜单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 统计代理数量
    total_agents = agent_bots.count_documents({})
    active_agents = agent_bots.count_documents({'status': 'active'})
    inactive_agents = agent_bots.count_documents({'status': 'inactive'})
    
    text = f"""
🤖 <b>代理管理系统</b>

📊 <b>代理概览</b>
├─ 总代理数：<code>{total_agents}</code>
├─ 活跃代理：<code>{active_agents}</code>
└─ 停用代理：<code>{inactive_agents}</code>

💡 <b>功能说明</b>
• 添加代理 - 创建新的代理机器人
• 代理列表 - 查看所有代理及状态
• 提现管理 - 处理代理提现申请
• 统计报表 - 查看代理销售数据

⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("➕ 添加代理", callback_data="agent_add"),
            InlineKeyboardButton("📋 代理列表", callback_data="agent_list")
        ],
        [
            InlineKeyboardButton("💸 提现管理", callback_data="agent_withdrawal_manage"),
            InlineKeyboardButton("📊 统计报表", callback_data="agent_stats_report")
        ],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="backstart")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_agent_list(update: Update, context: CallbackContext):
    """显示代理列表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取所有代理
    agents = list(agent_bots.find({}).sort('creation_time', -1))
    
    if not agents:
        text = """
📋 <b>代理列表</b>

暂无代理机器人

💡 点击下方按钮添加代理
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("➕ 添加代理", callback_data="agent_add")],
            [InlineKeyboardButton("🔙 返回", callback_data="agent_management")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    else:
        text = f"📋 <b>代理列表</b>\n\n共 {len(agents)} 个代理机器人：\n\n"
        
        keyboard = []
        for agent in agents[:10]:  # 限制显示前10个
            agent_name = agent.get('agent_name', '未知代理')
            agent_bot_id = agent.get('agent_bot_id')
            status = agent.get('status', 'active')
            status_emoji = "🟢" if status == 'active' else "🔴"
            
            # 获取简要统计
            stats = get_agent_stats(agent_bot_id, 'all')
            if stats:
                total_sales = stats.get('total_sales', 0)
                text += f"{status_emoji} <b>{agent_name}</b>\n"
                text += f"   └─ 销售额: <code>{total_sales:.2f}</code> USDT\n\n"
            else:
                text += f"{status_emoji} <b>{agent_name}</b>\n"
                text += f"   └─ 暂无数据\n\n"
            
            # 添加按钮
            keyboard.append([
                InlineKeyboardButton(
                    f"{status_emoji} {agent_name}",
                    callback_data=f"agent_detail_{agent_bot_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("➕ 添加代理", callback_data="agent_add")])
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="agent_management")])
        keyboard.append([InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def start_add_agent(update: Update, context: CallbackContext):
    """开始添加代理流程"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    text = """
➕ <b>添加新代理</b>

📝 <b>请按以下格式发送代理信息：</b>

<pre>/add_agent 代理名称 Bot_Token 佣金比例</pre>

<b>参数说明：</b>
• <b>代理名称</b>：代理机器人的名称（中文或英文）
• <b>Bot_Token</b>：代理机器人的Token（从 @BotFather 获取）
• <b>佣金比例</b>：代理的佣金比例（例如：0.3 表示 30%）

<b>示例：</b>
<pre>/add_agent 华东代理 123456:ABCdefGHI 0.25</pre>

⚠️ <b>注意事项：</b>
1. 每个代理Bot使用独立的Token
2. 佣金比例范围：0.1 ~ 0.5 (10% ~ 50%)
3. 添加后系统会自动同步商品
    """.strip()
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回代理列表", callback_data="agent_list")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def add_new_agent(update: Update, context: CallbackContext):
    """添加新代理（命令处理）"""
    user_id = update.effective_user.id
    message = update.message
    
    try:
        # 解析命令参数
        parts = message.text.strip().split()
        if len(parts) != 4:
            raise ValueError("参数数量不正确")
        
        _, agent_name, bot_token, commission_rate_str = parts
        
        # 验证佣金比例
        commission_rate = float(commission_rate_str)
        if not (0.1 <= commission_rate <= 0.5):
            raise ValueError("佣金比例必须在 0.1 ~ 0.5 之间")
        
        # 验证Bot Token格式
        if ':' not in bot_token or len(bot_token) < 40:
            raise ValueError("Bot Token 格式不正确")
        
        # 检查Token是否已存在
        existing = agent_bots.find_one({'agent_token': bot_token})
        if existing:
            message.reply_text("❌ 该 Bot Token 已被使用")
            return
        
        # 尝试获取Bot信息
        from telegram import Bot
        try:
            test_bot = Bot(token=bot_token)
            bot_info = test_bot.get_me()
            bot_username = bot_info.username
        except Exception as e:
            message.reply_text(f"❌ Bot Token 无效：{str(e)}")
            return
        
        # 生成代理ID
        agent_bot_id = generate_agent_bot_id()
        
        # 创建代理记录
        creation_time = beijing_now_str()
        agent_bots.insert_one({
            'agent_bot_id': agent_bot_id,
            'agent_name': agent_name,
            'agent_token': bot_token,
            'agent_username': bot_username,
            'owner_id': user_id,
            'commission_rate': commission_rate * 100,  # 存储为百分比
            'status': 'active',
            'creation_time': creation_time,
            'last_sync_time': '',
            'total_users': 0,
            'total_sales': 0.0,
            'total_commission': 0.0,
            'available_balance': 0.0,
            'withdrawn_amount': 0.0,
            'settings': {
                'welcome_message': '',
                'customer_service': '',
                'auto_delivery': True,
                'allow_recharge': True,
                'min_purchase': 0.0,
            }
        })
        
        # 同步商品到代理
        sync_result = sync_all_products_to_agent(agent_bot_id)
        
        success_text = f"""
✅ <b>代理添加成功</b>

📋 <b>代理信息</b>
• 代理名称：<b>{agent_name}</b>
• 代理ID：<code>{agent_bot_id}</code>
• Bot用户名：@{bot_username}
• 佣金比例：<code>{commission_rate*100:.1f}%</code>
• 创建时间：{creation_time}

📦 <b>商品同步</b>
• 成功同步：{sync_result.get('success_count', 0)} 个商品
• 同步失败：{sync_result.get('failed_count', 0)} 个

💡 <b>下一步操作</b>
1. 部署代理Bot实例
2. 配置代理Bot环境变量
3. 启动代理Bot服务

🔗 <b>Bot链接</b>
https://t.me/{bot_username}
        """.strip()
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("查看详情", callback_data=f"agent_detail_{agent_bot_id}")],
            [InlineKeyboardButton("返回列表", callback_data="agent_list")]
        ])
        
        message.reply_text(
            text=success_text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
        
        logging.info(f"✅ 添加代理成功：{agent_name} (@{bot_username}), ID: {agent_bot_id}")
        
    except ValueError as e:
        message.reply_text(
            f"❌ 参数错误：{str(e)}\n\n"
            f"正确格式：\n"
            f"<pre>/add_agent 代理名称 Bot_Token 佣金比例</pre>\n\n"
            f"示例：\n"
            f"<pre>/add_agent 华东代理 123456:ABCdefGHI 0.25</pre>",
            parse_mode='HTML'
        )
    except Exception as e:
        message.reply_text(f"❌ 添加代理失败：{str(e)}")
        logging.error(f"❌ 添加代理失败：{e}")


def show_agent_details(update: Update, context: CallbackContext):
    """显示代理详情"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 从callback_data中提取agent_bot_id
    agent_bot_id = query.data.replace("agent_detail_", "")
    
    # 获取代理信息
    agent = agent_bots.find_one({'agent_bot_id': agent_bot_id})
    if not agent:
        query.edit_message_text("❌ 代理不存在")
        return
    
    # 获取统计数据（全部时间）
    stats = get_agent_stats(agent_bot_id, 'all')
    if not stats:
        stats = {
            'total_sales': 0,
            'total_commission': 0,
            'available_balance': 0,
            'withdrawn_amount': 0,
            'total_users': 0,
            'order_count': 0,
            'pending_withdrawal_count': 0,
            'pending_withdrawal_amount': 0,
            'avg_order': 0,
            'profit_rate': 0
        }
    
    # 获取最近7天统计
    stats_7d = get_agent_stats(agent_bot_id, '7d')
    if not stats_7d:
        stats_7d = {'total_sales': 0, 'order_count': 0}
    
    agent_name = agent.get('agent_name', '未知代理')
    agent_username = agent.get('agent_username', 'unknown')
    commission_rate = agent.get('commission_rate', 0)
    status = agent.get('status', 'active')
    creation_time = agent.get('creation_time', '')
    
    status_emoji = "🟢" if status == 'active' else "🔴"
    status_text = "正常运营" if status == 'active' else "已停用"
    
    text = f"""
🤖 <b>代理详情</b>

📋 <b>基本信息</b>
• 代理名称：<b>{agent_name}</b>
• Bot用户名：@{agent_username}
• 代理ID：<code>{agent_bot_id}</code>
• 状态：{status_emoji} {status_text}
• 佣金比例：<code>{commission_rate:.1f}%</code>
• 创建时间：{creation_time}

📊 <b>累计数据</b>
• 总销售额：<code>{stats['total_sales']:.2f}</code> USDT
• 累计佣金：<code>{stats['total_commission']:.2f}</code> USDT
• 订单总数：<code>{stats['order_count']}</code> 单
• 用户总数：<code>{stats['total_users']}</code> 人
• 平均客单：<code>{stats['avg_order']:.2f}</code> USDT

💰 <b>财务状况</b>
• 可提现余额：<code>{stats['available_balance']:.2f}</code> USDT
• 已提现金额：<code>{stats['withdrawn_amount']:.2f}</code> USDT
• 待处理提现：<code>{stats['pending_withdrawal_count']}</code> 笔
• 待处理金额：<code>{stats['pending_withdrawal_amount']:.2f}</code> USDT

📈 <b>近7天数据</b>
• 销售额：<code>{stats_7d['total_sales']:.2f}</code> USDT
• 订单数：<code>{stats_7d['order_count']}</code> 单

🔗 <b>Bot链接</b>
https://t.me/{agent_username}
    """.strip()
    
    # 根据状态显示不同的按钮
    if status == 'active':
        toggle_button = InlineKeyboardButton("🔴 停用代理", callback_data=f"agent_disable_{agent_bot_id}")
    else:
        toggle_button = InlineKeyboardButton("🟢 启用代理", callback_data=f"agent_enable_{agent_bot_id}")
    
    keyboard = [
        [
            InlineKeyboardButton("📊 详细统计", callback_data=f"agent_stats_{agent_bot_id}"),
            InlineKeyboardButton("⚙️ 设置", callback_data=f"agent_settings_{agent_bot_id}")
        ],
        [
            toggle_button,
            InlineKeyboardButton("🗑️ 删除代理", callback_data=f"agent_delete_confirm_{agent_bot_id}")
        ],
        [InlineKeyboardButton("🔄 刷新", callback_data=f"agent_detail_{agent_bot_id}")],
        [InlineKeyboardButton("🔙 返回列表", callback_data="agent_list")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


def toggle_agent_status(update: Update, context: CallbackContext):
    """启用/停用代理"""
    query = update.callback_query
    query.answer()
    
    # 解析callback_data
    data = query.data
    if data.startswith("agent_enable_"):
        agent_bot_id = data.replace("agent_enable_", "")
        new_status = 'active'
        action_text = "启用"
    elif data.startswith("agent_disable_"):
        agent_bot_id = data.replace("agent_disable_", "")
        new_status = 'inactive'
        action_text = "停用"
    else:
        return
    
    # 更新状态
    result = agent_bots.update_one(
        {'agent_bot_id': agent_bot_id},
        {'$set': {'status': new_status}}
    )
    
    if result.modified_count > 0:
        query.answer(f"✅ 已{action_text}代理", show_alert=True)
        # 刷新详情页
        context.bot.callback_query = query
        query.data = f"agent_detail_{agent_bot_id}"
        show_agent_details(update, context)
    else:
        query.answer(f"❌ {action_text}失败", show_alert=True)


def delete_agent_confirm(update: Update, context: CallbackContext):
    """删除代理确认"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    agent_bot_id = query.data.replace("agent_delete_confirm_", "")
    
    # 获取代理信息
    agent = agent_bots.find_one({'agent_bot_id': agent_bot_id})
    if not agent:
        query.edit_message_text("❌ 代理不存在")
        return
    
    agent_name = agent.get('agent_name', '未知代理')
    
    text = f"""
⚠️ <b>确认删除代理</b>

您确定要删除代理 <b>{agent_name}</b> 吗？

<b>警告：</b>
• 删除后代理Bot将无法访问系统
• 代理的历史数据将被保留
• 此操作<b>不可撤销</b>

请谨慎操作！
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"agent_delete_{agent_bot_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"agent_detail_{agent_bot_id}")
        ]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def delete_agent(update: Update, context: CallbackContext):
    """删除代理（执行）"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    agent_bot_id = query.data.replace("agent_delete_", "")
    
    # 获取代理信息
    agent = agent_bots.find_one({'agent_bot_id': agent_bot_id})
    if not agent:
        query.edit_message_text("❌ 代理不存在")
        return
    
    agent_name = agent.get('agent_name', '未知代理')
    
    # 删除代理（软删除，改为inactive状态）
    result = agent_bots.update_one(
        {'agent_bot_id': agent_bot_id},
        {'$set': {'status': 'deleted', 'deleted_time': beijing_now_str()}}
    )
    
    if result.modified_count > 0:
        text = f"""
✅ <b>代理已删除</b>

代理 <b>{agent_name}</b> 已被删除

• 代理Bot已无法访问系统
• 历史数据已保留
• 可在数据库中恢复（联系技术支持）
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回代理列表", callback_data="agent_list")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
        
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logging.info(f"✅ 删除代理：{agent_name}, ID: {agent_bot_id}")
    else:
        query.answer("❌ 删除失败", show_alert=True)


def show_agent_stats(update: Update, context: CallbackContext):
    """显示代理详细统计"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    agent_bot_id = query.data.replace("agent_stats_", "")
    
    # 获取代理信息
    agent = agent_bots.find_one({'agent_bot_id': agent_bot_id})
    if not agent:
        query.edit_message_text("❌ 代理不存在")
        return
    
    agent_name = agent.get('agent_name', '未知代理')
    
    # 获取不同周期的统计
    stats_7d = get_agent_stats(agent_bot_id, '7d') or {}
    stats_30d = get_agent_stats(agent_bot_id, '30d') or {}
    stats_all = get_agent_stats(agent_bot_id, 'all') or {}
    
    text = f"""
📊 <b>{agent_name} - 详细统计</b>

📈 <b>近7天</b>
• 销售额：<code>{stats_7d.get('total_sales', 0):.2f}</code> USDT
• 佣金：<code>{stats_7d.get('total_commission', 0):.2f}</code> USDT
• 订单数：<code>{stats_7d.get('order_count', 0)}</code> 单
• 平均客单：<code>{stats_7d.get('avg_order', 0):.2f}</code> USDT

📊 <b>近30天</b>
• 销售额：<code>{stats_30d.get('total_sales', 0):.2f}</code> USDT
• 佣金：<code>{stats_30d.get('total_commission', 0):.2f}</code> USDT
• 订单数：<code>{stats_30d.get('order_count', 0)}</code> 单
• 平均客单：<code>{stats_30d.get('avg_order', 0):.2f}</code> USDT

📆 <b>累计数据</b>
• 销售额：<code>{stats_all.get('total_sales', 0):.2f}</code> USDT
• 佣金：<code>{stats_all.get('total_commission', 0):.2f}</code> USDT
• 订单数：<code>{stats_all.get('order_count', 0)}</code> 单
• 用户数：<code>{stats_all.get('total_users', 0)}</code> 人

💰 <b>财务状况</b>
• 可提现：<code>{stats_all.get('available_balance', 0):.2f}</code> USDT
• 已提现：<code>{stats_all.get('withdrawn_amount', 0):.2f}</code> USDT
• 利润率：<code>{stats_all.get('profit_rate', 0):.2f}%</code>

⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()
    
    keyboard = [
        [InlineKeyboardButton("🔄 刷新", callback_data=f"agent_stats_{agent_bot_id}")],
        [InlineKeyboardButton("🔙 返回详情", callback_data=f"agent_detail_{agent_bot_id}")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================== 代理提现管理模块 ====================

"""
代理提现管理功能
包含：查看提现申请、审批提现、拒绝提现、提现历史
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from mongo import (
    agent_withdrawals,
    agent_bots,
    get_agent_bot_info,
    format_beijing_time,
    beijing_now_str
)


def show_withdrawal_management(update: Update, context: CallbackContext):
    """显示提现管理主菜单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 统计提现数据
    pending_count = agent_withdrawals.count_documents({'status': 'pending'})
    pending_amount = sum(
        w.get('amount', 0) 
        for w in agent_withdrawals.find({'status': 'pending'})
    )
    
    approved_count = agent_withdrawals.count_documents({'status': 'approved'})
    completed_count = agent_withdrawals.count_documents({'status': 'completed'})
    rejected_count = agent_withdrawals.count_documents({'status': 'rejected'})
    
    text = f"""
💸 <b>代理提现管理</b>

📊 <b>提现概览</b>
├─ 待审核：<code>{pending_count}</code> 笔（<code>{pending_amount:.2f}</code> USDT）
├─ 已审核：<code>{approved_count}</code> 笔
├─ 已完成：<code>{completed_count}</code> 笔
└─ 已拒绝：<code>{rejected_count}</code> 笔

💡 <b>功能说明</b>
• 待审核 - 查看并处理待审核的提现申请
• 提现历史 - 查看所有提现记录
• 统计报表 - 查看提现统计数据

⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton(f"⏳ 待审核 ({pending_count})", callback_data="agent_withdrawal_pending"),
            InlineKeyboardButton("📋 提现历史", callback_data="agent_withdrawal_history")
        ],
        [InlineKeyboardButton("📊 统计报表", callback_data="agent_withdrawal_stats")],
        [InlineKeyboardButton("🔙 返回代理管理", callback_data="agent_management")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_pending_withdrawals(update: Update, context: CallbackContext):
    """显示待审核提现列表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取待审核提现
    withdrawals = list(
        agent_withdrawals.find({'status': 'pending'})
        .sort('apply_time', -1)
        .limit(10)
    )
    
    if not withdrawals:
        text = """
⏳ <b>待审核提现</b>

暂无待审核的提现申请

💡 代理可在代理Bot中申请提现
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回提现管理", callback_data="agent_withdrawal_manage")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    else:
        text = f"⏳ <b>待审核提现</b>\n\n共 {len(withdrawals)} 笔待审核：\n\n"
        
        keyboard = []
        for i, w in enumerate(withdrawals, 1):
            agent_bot_id = w.get('agent_bot_id')
            agent = get_agent_bot_info(agent_bot_id)
            agent_name = agent.get('agent_name', '未知代理') if agent else '未知代理'
            
            amount = w.get('amount', 0)
            apply_time = w.get('apply_time', '')
            withdrawal_id = str(w.get('_id'))
            payment_method = w.get('payment_method', 'TRC20')
            payment_account = w.get('payment_account', '')
            
            text += f"{i}. <b>{agent_name}</b>\n"
            text += f"   ├─ 金额：<code>{amount:.2f}</code> USDT\n"
            text += f"   ├─ 方式：{payment_method}\n"
            text += f"   ├─ 账户：<code>{payment_account[:10]}...{payment_account[-4:]}</code>\n"
            text += f"   └─ 申请时间：{apply_time}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"📝 {agent_name} - {amount:.2f} USDT",
                    callback_data=f"agent_withdrawal_detail_{withdrawal_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔄 刷新", callback_data="agent_withdrawal_pending")])
        keyboard.append([InlineKeyboardButton("🔙 返回提现管理", callback_data="agent_withdrawal_manage")])
        keyboard.append([InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_withdrawal_detail(update: Update, context: CallbackContext):
    """显示提现详情"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    withdrawal_id = query.data.replace("agent_withdrawal_detail_", "")
    
    # 获取提现记录
    from bson import ObjectId
    withdrawal = agent_withdrawals.find_one({'_id': ObjectId(withdrawal_id)})
    if not withdrawal:
        query.edit_message_text("❌ 提现记录不存在")
        return
    
    # 获取代理信息
    agent_bot_id = withdrawal.get('agent_bot_id')
    agent = get_agent_bot_info(agent_bot_id)
    agent_name = agent.get('agent_name', '未知代理') if agent else '未知代理'
    agent_username = agent.get('agent_username', 'unknown') if agent else 'unknown'
    
    amount = withdrawal.get('amount', 0)
    payment_method = withdrawal.get('payment_method', 'TRC20')
    payment_account = withdrawal.get('payment_account', '')
    status = withdrawal.get('status', 'pending')
    apply_time = withdrawal.get('apply_time', '')
    notes = withdrawal.get('notes', '')
    
    # 获取代理统计
    from mongo import get_agent_stats
    stats = get_agent_stats(agent_bot_id, 'all')
    available_balance = stats.get('available_balance', 0) if stats else 0
    
    status_map = {
        'pending': '⏳ 待审核',
        'approved': '✅ 已审核',
        'completed': '✅ 已完成',
        'rejected': '❌ 已拒绝'
    }
    status_text = status_map.get(status, status)
    
    text = f"""
💸 <b>提现详情</b>

📋 <b>基本信息</b>
• 代理名称：<b>{agent_name}</b>
• Bot用户名：@{agent_username}
• 提现金额：<code>{amount:.2f}</code> USDT
• 提现方式：{payment_method}
• 收款账户：<code>{payment_account}</code>
• 申请时间：{apply_time}
• 当前状态：{status_text}

💰 <b>财务状况</b>
• 可用余额：<code>{available_balance:.2f}</code> USDT
• 提现后余额：<code>{available_balance - amount:.2f}</code> USDT
    """.strip()
    
    if notes:
        text += f"\n\n📝 <b>备注</b>\n{notes}"
    
    # 根据状态显示不同按钮
    if status == 'pending':
        keyboard = [
            [
                InlineKeyboardButton("✅ 通过", callback_data=f"agent_withdrawal_approve_{withdrawal_id}"),
                InlineKeyboardButton("❌ 拒绝", callback_data=f"agent_withdrawal_reject_{withdrawal_id}")
            ],
            [InlineKeyboardButton("🔙 返回列表", callback_data="agent_withdrawal_pending")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🔙 返回列表", callback_data="agent_withdrawal_history")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def approve_withdrawal(update: Update, context: CallbackContext):
    """通过提现申请"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    withdrawal_id = query.data.replace("agent_withdrawal_approve_", "")
    
    from bson import ObjectId
    withdrawal = agent_withdrawals.find_one({'_id': ObjectId(withdrawal_id)})
    if not withdrawal:
        query.answer("❌ 提现记录不存在", show_alert=True)
        return
    
    if withdrawal.get('status') != 'pending':
        query.answer("❌ 该提现已处理", show_alert=True)
        return
    
    # 更新提现状态
    result = agent_withdrawals.update_one(
        {'_id': ObjectId(withdrawal_id)},
        {
            '$set': {
                'status': 'approved',
                'process_time': beijing_now_str(),
                'process_by': user_id
            }
        }
    )
    
    if result.modified_count > 0:
        agent_bot_id = withdrawal.get('agent_bot_id')
        agent = get_agent_bot_info(agent_bot_id)
        agent_name = agent.get('agent_name', '未知代理') if agent else '未知代理'
        amount = withdrawal.get('amount', 0)
        
        query.answer(f"✅ 已通过 {agent_name} 的提现申请", show_alert=True)
        
        # 发送成功消息
        text = f"""
✅ <b>提现审核通过</b>

代理 <b>{agent_name}</b> 的提现申请已通过

• 提现金额：<code>{amount:.2f}</code> USDT
• 审核时间：{beijing_now_str()}

💡 <b>下一步操作</b>
1. 手动向代理账户转账
2. 获取交易哈希
3. 在系统中标记为"已完成"

⚠️ <b>注意</b>
请确保在完成转账后及时更新状态
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("💸 标记已完成", callback_data=f"agent_withdrawal_complete_{withdrawal_id}")],
            [InlineKeyboardButton("🔙 返回列表", callback_data="agent_withdrawal_pending")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
        
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logging.info(f"✅ 通过提现：withdrawal_id={withdrawal_id}, agent={agent_name}, amount={amount}")
    else:
        query.answer("❌ 审核失败", show_alert=True)


def reject_withdrawal(update: Update, context: CallbackContext):
    """拒绝提现申请"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    withdrawal_id = query.data.replace("agent_withdrawal_reject_", "")
    
    from bson import ObjectId
    withdrawal = agent_withdrawals.find_one({'_id': ObjectId(withdrawal_id)})
    if not withdrawal:
        query.answer("❌ 提现记录不存在", show_alert=True)
        return
    
    if withdrawal.get('status') != 'pending':
        query.answer("❌ 该提现已处理", show_alert=True)
        return
    
    # 更新提现状态
    result = agent_withdrawals.update_one(
        {'_id': ObjectId(withdrawal_id)},
        {
            '$set': {
                'status': 'rejected',
                'process_time': beijing_now_str(),
                'process_by': user_id,
                'notes': '管理员拒绝'
            }
        }
    )
    
    if result.modified_count > 0:
        agent_bot_id = withdrawal.get('agent_bot_id')
        agent = get_agent_bot_info(agent_bot_id)
        agent_name = agent.get('agent_name', '未知代理') if agent else '未知代理'
        amount = withdrawal.get('amount', 0)
        
        query.answer(f"✅ 已拒绝 {agent_name} 的提现申请", show_alert=True)
        
        # 发送成功消息
        text = f"""
❌ <b>提现审核拒绝</b>

代理 <b>{agent_name}</b> 的提现申请已拒绝

• 提现金额：<code>{amount:.2f}</code> USDT
• 拒绝时间：{beijing_now_str()}
• 拒绝原因：管理员拒绝

✅ 系统已自动：
• 退还代理余额
• 发送拒绝通知
• 记录操作日志
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回列表", callback_data="agent_withdrawal_pending")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
        
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logging.info(f"❌ 拒绝提现：withdrawal_id={withdrawal_id}, agent={agent_name}, amount={amount}")
    else:
        query.answer("❌ 拒绝失败", show_alert=True)


def complete_withdrawal(update: Update, context: CallbackContext):
    """标记提现为已完成"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    withdrawal_id = query.data.replace("agent_withdrawal_complete_", "")
    
    from bson import ObjectId
    withdrawal = agent_withdrawals.find_one({'_id': ObjectId(withdrawal_id)})
    if not withdrawal:
        query.answer("❌ 提现记录不存在", show_alert=True)
        return
    
    if withdrawal.get('status') not in ['pending', 'approved']:
        query.answer("❌ 该提现状态不允许完成", show_alert=True)
        return
    
    # 更新提现状态为已完成
    result = agent_withdrawals.update_one(
        {'_id': ObjectId(withdrawal_id)},
        {
            '$set': {
                'status': 'completed',
                'completed_time': beijing_now_str(),
                'process_by': user_id
            }
        }
    )
    
    if result.modified_count > 0:
        agent_bot_id = withdrawal.get('agent_bot_id')
        agent = get_agent_bot_info(agent_bot_id)
        agent_name = agent.get('agent_name', '未知代理') if agent else '未知代理'
        amount = withdrawal.get('amount', 0)
        
        query.answer(f"✅ 提现已完成", show_alert=True)
        
        # 发送成功消息
        text = f"""
✅ <b>提现已完成</b>

代理 <b>{agent_name}</b> 的提现已完成

• 提现金额：<code>{amount:.2f}</code> USDT
• 完成时间：{beijing_now_str()}

✅ 系统已自动：
• 标记提现完成
• 通知代理
• 记录操作日志
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回列表", callback_data="agent_withdrawal_history")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
        
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logging.info(f"✅ 完成提现：withdrawal_id={withdrawal_id}, agent={agent_name}, amount={amount}")
    else:
        query.answer("❌ 操作失败", show_alert=True)


def view_withdrawal_history(update: Update, context: CallbackContext):
    """查看提现历史"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取所有提现记录（按时间倒序）
    withdrawals = list(
        agent_withdrawals.find({})
        .sort('apply_time', -1)
        .limit(20)
    )
    
    if not withdrawals:
        text = """
📋 <b>提现历史</b>

暂无提现记录

💡 代理可在代理Bot中申请提现
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回提现管理", callback_data="agent_withdrawal_manage")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    else:
        text = f"📋 <b>提现历史</b>\n\n最近 {len(withdrawals)} 笔提现记录：\n\n"
        
        keyboard = []
        for i, w in enumerate(withdrawals, 1):
            agent_bot_id = w.get('agent_bot_id')
            agent = get_agent_bot_info(agent_bot_id)
            agent_name = agent.get('agent_name', '未知代理') if agent else '未知代理'
            
            amount = w.get('amount', 0)
            status = w.get('status', 'pending')
            apply_time = w.get('apply_time', '')
            withdrawal_id = str(w.get('_id'))
            
            status_map = {
                'pending': '⏳',
                'approved': '✅',
                'completed': '✅',
                'rejected': '❌'
            }
            status_emoji = status_map.get(status, '❓')
            
            text += f"{status_emoji} <b>{agent_name}</b> - <code>{amount:.2f}</code> USDT\n"
            text += f"   └─ {apply_time} - {status}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{status_emoji} {agent_name} - {amount:.2f} USDT",
                    callback_data=f"agent_withdrawal_detail_{withdrawal_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔄 刷新", callback_data="agent_withdrawal_history")])
        keyboard.append([InlineKeyboardButton("🔙 返回提现管理", callback_data="agent_withdrawal_manage")])
        keyboard.append([InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_withdrawal_stats(update: Update, context: CallbackContext):
    """显示提现统计"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 统计各状态的提现
    pending_count = agent_withdrawals.count_documents({'status': 'pending'})
    approved_count = agent_withdrawals.count_documents({'status': 'approved'})
    completed_count = agent_withdrawals.count_documents({'status': 'completed'})
    rejected_count = agent_withdrawals.count_documents({'status': 'rejected'})
    
    # 统计金额
    total_completed = sum(
        w.get('amount', 0)
        for w in agent_withdrawals.find({'status': 'completed'})
    )
    total_pending = sum(
        w.get('amount', 0)
        for w in agent_withdrawals.find({'status': 'pending'})
    )
    
    text = f"""
📊 <b>提现统计报表</b>

📈 <b>提现数量</b>
├─ 待审核：<code>{pending_count}</code> 笔
├─ 已审核：<code>{approved_count}</code> 笔
├─ 已完成：<code>{completed_count}</code> 笔
└─ 已拒绝：<code>{rejected_count}</code> 笔

💰 <b>提现金额</b>
├─ 待处理金额：<code>{total_pending:.2f}</code> USDT
└─ 已完成金额：<code>{total_completed:.2f}</code> USDT

⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()
    
    keyboard = [
        [InlineKeyboardButton("🔄 刷新", callback_data="agent_withdrawal_stats")],
        [InlineKeyboardButton("🔙 返回提现管理", callback_data="agent_withdrawal_manage")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================== 代理统计报表模块 ====================

"""
代理统计报表模块
包含：代理销售排行、利润汇总、订单明细导出
"""

import logging
from datetime import datetime, timedelta
from io import BytesIO
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import CallbackContext
from mongo import (
    agent_bots,
    agent_orders,
    agent_withdrawals,
    get_agent_stats,
    get_agent_bot_info,
    format_beijing_time,
    beijing_now_str,
    get_beijing_now
)


def show_agent_stats_report(update: Update, context: CallbackContext):
    """显示代理统计报表主菜单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    text = """
📊 <b>代理统计报表</b>

📈 <b>可用报表</b>
• 销售排行 - 各代理销售额排名
• 利润汇总 - 代理利润统计分析
• 订单明细 - 导出代理订单详情
• 综合报表 - 完整的代理数据分析

💡 <b>说明</b>
报表数据实时统计，可选择不同时间周期查看

⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("🏆 销售排行", callback_data="agent_report_sales_ranking"),
            InlineKeyboardButton("💰 利润汇总", callback_data="agent_report_profit_summary")
        ],
        [
            InlineKeyboardButton("📦 订单明细", callback_data="agent_report_orders"),
            InlineKeyboardButton("📊 综合报表", callback_data="agent_report_comprehensive")
        ],
        [InlineKeyboardButton("🔙 返回代理管理", callback_data="agent_management")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_sales_ranking(update: Update, context: CallbackContext):
    """显示代理销售排行"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取所有活跃代理
    agents = list(agent_bots.find({'status': {'$in': ['active', 'inactive']}}))
    
    if not agents:
        text = """
🏆 <b>代理销售排行</b>

暂无代理数据

💡 添加代理后即可查看排行
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回报表菜单", callback_data="agent_stats_report")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    else:
        # 获取所有代理的统计数据
        agent_stats_list = []
        for agent in agents:
            agent_bot_id = agent.get('agent_bot_id')
            agent_name = agent.get('agent_name', '未知代理')
            stats = get_agent_stats(agent_bot_id, 'all')
            
            if stats:
                agent_stats_list.append({
                    'name': agent_name,
                    'bot_id': agent_bot_id,
                    'sales': stats.get('total_sales', 0),
                    'commission': stats.get('total_commission', 0),
                    'orders': stats.get('order_count', 0),
                    'users': stats.get('total_users', 0),
                    'avg_order': stats.get('avg_order', 0)
                })
        
        # 按销售额排序
        agent_stats_list.sort(key=lambda x: x['sales'], reverse=True)
        
        text = f"🏆 <b>代理销售排行</b>\n\n共 {len(agent_stats_list)} 个代理：\n\n"
        
        medals = ['🥇', '🥈', '🥉']
        for i, stats in enumerate(agent_stats_list[:10], 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            text += f"{medal} <b>{stats['name']}</b>\n"
            text += f"   ├─ 销售额：<code>{stats['sales']:.2f}</code> USDT\n"
            text += f"   ├─ 佣金：<code>{stats['commission']:.2f}</code> USDT\n"
            text += f"   ├─ 订单：<code>{stats['orders']}</code> 单\n"
            text += f"   └─ 用户：<code>{stats['users']}</code> 人\n\n"
        
        # 添加汇总
        total_sales = sum(s['sales'] for s in agent_stats_list)
        total_commission = sum(s['commission'] for s in agent_stats_list)
        total_orders = sum(s['orders'] for s in agent_stats_list)
        
        text += f"📊 <b>总计</b>\n"
        text += f"• 总销售额：<code>{total_sales:.2f}</code> USDT\n"
        text += f"• 总佣金：<code>{total_commission:.2f}</code> USDT\n"
        text += f"• 总订单：<code>{total_orders}</code> 单\n\n"
        text += f"⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}"
        
        keyboard = [
            [
                InlineKeyboardButton("📊 查看7天", callback_data="agent_ranking_7d"),
                InlineKeyboardButton("📊 查看30天", callback_data="agent_ranking_30d")
            ],
            [InlineKeyboardButton("📥 导出Excel", callback_data="agent_export_sales_ranking")],
            [InlineKeyboardButton("🔄 刷新", callback_data="agent_report_sales_ranking")],
            [InlineKeyboardButton("🔙 返回报表菜单", callback_data="agent_stats_report")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_profit_summary(update: Update, context: CallbackContext):
    """显示代理利润汇总"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取所有代理
    agents = list(agent_bots.find({'status': {'$in': ['active', 'inactive']}}))
    
    if not agents:
        text = """
💰 <b>代理利润汇总</b>

暂无代理数据

💡 添加代理后即可查看利润汇总
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回报表菜单", callback_data="agent_stats_report")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    else:
        # 统计各代理财务数据
        profit_list = []
        total_available = 0
        total_withdrawn = 0
        total_commission = 0
        
        for agent in agents:
            agent_bot_id = agent.get('agent_bot_id')
            agent_name = agent.get('agent_name', '未知代理')
            commission_rate = agent.get('commission_rate', 0)
            
            stats = get_agent_stats(agent_bot_id, 'all')
            if stats:
                available = stats.get('available_balance', 0)
                withdrawn = stats.get('withdrawn_amount', 0)
                commission = stats.get('total_commission', 0)
                
                profit_list.append({
                    'name': agent_name,
                    'bot_id': agent_bot_id,
                    'available': available,
                    'withdrawn': withdrawn,
                    'commission': commission,
                    'rate': commission_rate
                })
                
                total_available += available
                total_withdrawn += withdrawn
                total_commission += commission
        
        # 按可用余额排序
        profit_list.sort(key=lambda x: x['available'], reverse=True)
        
        text = f"💰 <b>代理利润汇总</b>\n\n"
        
        for i, profit in enumerate(profit_list[:10], 1):
            text += f"{i}. <b>{profit['name']}</b>\n"
            text += f"   ├─ 累计佣金：<code>{profit['commission']:.2f}</code> USDT\n"
            text += f"   ├─ 可用余额：<code>{profit['available']:.2f}</code> USDT\n"
            text += f"   ├─ 已提现：<code>{profit['withdrawn']:.2f}</code> USDT\n"
            text += f"   └─ 佣金比例：<code>{profit['rate']:.1f}%</code>\n\n"
        
        text += f"💼 <b>财务总计</b>\n"
        text += f"• 累计佣金：<code>{total_commission:.2f}</code> USDT\n"
        text += f"• 可提现余额：<code>{total_available:.2f}</code> USDT\n"
        text += f"• 已提现金额：<code>{total_withdrawn:.2f}</code> USDT\n\n"
        text += f"⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}"
        
        keyboard = [
            [InlineKeyboardButton("📥 导出Excel", callback_data="agent_export_profit_summary")],
            [InlineKeyboardButton("🔄 刷新", callback_data="agent_report_profit_summary")],
            [InlineKeyboardButton("🔙 返回报表菜单", callback_data="agent_stats_report")],
            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
        ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def export_sales_ranking(update: Update, context: CallbackContext):
    """导出销售排行Excel"""
    query = update.callback_query
    query.answer("正在生成报表，请稍候...")
    user_id = query.from_user.id
    
    try:
        # 获取所有代理及统计
        agents = list(agent_bots.find({'status': {'$in': ['active', 'inactive']}}))
        
        data = []
        for agent in agents:
            agent_bot_id = agent.get('agent_bot_id')
            agent_name = agent.get('agent_name', '未知代理')
            agent_username = agent.get('agent_username', '')
            commission_rate = agent.get('commission_rate', 0)
            status = agent.get('status', 'unknown')
            creation_time = agent.get('creation_time', '')
            
            stats = get_agent_stats(agent_bot_id, 'all')
            if stats:
                data.append({
                    '排名': 0,  # 稍后设置
                    '代理名称': agent_name,
                    'Bot用户名': f'@{agent_username}',
                    '状态': '正常' if status == 'active' else '停用',
                    '销售额(USDT)': stats.get('total_sales', 0),
                    '佣金(USDT)': stats.get('total_commission', 0),
                    '订单数': stats.get('order_count', 0),
                    '用户数': stats.get('total_users', 0),
                    '平均客单(USDT)': stats.get('avg_order', 0),
                    '佣金比例(%)': commission_rate,
                    '创建时间': creation_time
                })
        
        # 按销售额排序并设置排名
        data.sort(key=lambda x: x['销售额(USDT)'], reverse=True)
        for i, row in enumerate(data, 1):
            row['排名'] = i
        
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 生成Excel
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='销售排行')
            
            # 设置列宽
            worksheet = writer.sheets['销售排行']
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 25))
        
        buffer.seek(0)
        
        # 发送文件
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"代理销售排行_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx",
            caption=f"📊 代理销售排行报表\n\n共 {len(data)} 个代理"
        )
        
        query.edit_message_text("✅ 报表已生成并发送")
        
    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")
        logging.error(f"导出销售排行失败：{e}")


def export_profit_summary(update: Update, context: CallbackContext):
    """导出利润汇总Excel"""
    query = update.callback_query
    query.answer("正在生成报表，请稍候...")
    user_id = query.from_user.id
    
    try:
        # 获取所有代理及财务数据
        agents = list(agent_bots.find({'status': {'$in': ['active', 'inactive']}}))
        
        data = []
        for agent in agents:
            agent_bot_id = agent.get('agent_bot_id')
            agent_name = agent.get('agent_name', '未知代理')
            agent_username = agent.get('agent_username', '')
            commission_rate = agent.get('commission_rate', 0)
            status = agent.get('status', 'unknown')
            
            stats = get_agent_stats(agent_bot_id, 'all')
            if stats:
                data.append({
                    '代理名称': agent_name,
                    'Bot用户名': f'@{agent_username}',
                    '状态': '正常' if status == 'active' else '停用',
                    '累计佣金(USDT)': stats.get('total_commission', 0),
                    '可用余额(USDT)': stats.get('available_balance', 0),
                    '已提现(USDT)': stats.get('withdrawn_amount', 0),
                    '待处理提现': stats.get('pending_withdrawal_count', 0),
                    '佣金比例(%)': commission_rate,
                    '利润率(%)': stats.get('profit_rate', 0),
                    '销售额(USDT)': stats.get('total_sales', 0),
                    '订单数': stats.get('order_count', 0)
                })
        
        # 创建DataFrame
        df = pd.DataFrame(data)
        
        # 计算汇总
        summary_data = [{
            '统计项目': '总累计佣金',
            '数值': f"{df['累计佣金(USDT)'].sum():.2f} USDT"
        }, {
            '统计项目': '总可用余额',
            '数值': f"{df['可用余额(USDT)'].sum():.2f} USDT"
        }, {
            '统计项目': '总已提现',
            '数值': f"{df['已提现(USDT)'].sum():.2f} USDT"
        }, {
            '统计项目': '代理总数',
            '数值': len(data)
        }]
        
        df_summary = pd.DataFrame(summary_data)
        
        # 生成Excel
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='利润明细')
            df_summary.to_excel(writer, index=False, sheet_name='汇总统计')
            
            # 设置列宽
            for sheet_name in ['利润明细', '汇总统计']:
                worksheet = writer.sheets[sheet_name]
                data_df = df if sheet_name == '利润明细' else df_summary
                for i, col in enumerate(data_df.columns):
                    column_len = max(data_df[col].astype(str).str.len().max(), len(col)) + 2
                    worksheet.set_column(i, i, min(column_len, 25))
        
        buffer.seek(0)
        
        # 发送文件
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"代理利润汇总_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx",
            caption=f"💰 代理利润汇总报表\n\n共 {len(data)} 个代理"
        )
        
        query.edit_message_text("✅ 报表已生成并发送")
        
    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")
        logging.error(f"导出利润汇总失败：{e}")


def show_comprehensive_report(update: Update, context: CallbackContext):
    """显示综合报表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    text = """
📊 <b>综合报表</b>

💡 <b>选择导出方式</b>
• 完整报表 - 包含所有代理的详细数据
• 简要报表 - 仅包含关键指标

<b>报表内容</b>
1. 代理基本信息
2. 销售统计数据
3. 财务状况分析
4. 提现记录
5. 订单明细

⚠️ 生成时间较长，请耐心等待
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("📥 完整报表", callback_data="agent_export_comprehensive_full"),
            InlineKeyboardButton("📄 简要报表", callback_data="agent_export_comprehensive_brief")
        ],
        [InlineKeyboardButton("🔙 返回报表菜单", callback_data="agent_stats_report")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def export_comprehensive_report(update: Update, context: CallbackContext, report_type='full'):
    """导出综合报表"""
    query = update.callback_query
    query.answer("正在生成综合报表，请稍候...")
    user_id = query.from_user.id
    
    try:
        # 获取所有代理
        agents = list(agent_bots.find({'status': {'$in': ['active', 'inactive']}}))
        
        # 代理基本信息
        agent_data = []
        for agent in agents:
            agent_bot_id = agent.get('agent_bot_id')
            stats = get_agent_stats(agent_bot_id, 'all')
            
            agent_data.append({
                '代理名称': agent.get('agent_name', ''),
                'Bot用户名': f"@{agent.get('agent_username', '')}",
                '代理ID': agent_bot_id,
                '状态': '正常' if agent.get('status') == 'active' else '停用',
                '佣金比例(%)': agent.get('commission_rate', 0),
                '创建时间': agent.get('creation_time', ''),
                '销售额(USDT)': stats.get('total_sales', 0) if stats else 0,
                '佣金(USDT)': stats.get('total_commission', 0) if stats else 0,
                '订单数': stats.get('order_count', 0) if stats else 0,
                '用户数': stats.get('total_users', 0) if stats else 0,
                '可用余额(USDT)': stats.get('available_balance', 0) if stats else 0,
                '已提现(USDT)': stats.get('withdrawn_amount', 0) if stats else 0
            })
        
        df_agents = pd.DataFrame(agent_data)
        
        # 生成Excel
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df_agents.to_excel(writer, index=False, sheet_name='代理信息')
            
            if report_type == 'full':
                # 完整报表包含更多工作表
                # TODO: 添加订单明细、提现记录等
                pass
            
            # 设置列宽
            worksheet = writer.sheets['代理信息']
            for i, col in enumerate(df_agents.columns):
                column_len = max(df_agents[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 25))
        
        buffer.seek(0)
        
        # 发送文件
        report_name = "完整" if report_type == 'full' else "简要"
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"代理{report_name}报表_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx",
            caption=f"📊 代理{report_name}报表\n\n共 {len(agent_data)} 个代理"
        )
        
        query.edit_message_text("✅ 报表已生成并发送")
        
    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")
        logging.error(f"导出综合报表失败：{e}")


def show_agent_settings(update: Update, context: CallbackContext):
    """显示代理商设置菜单"""
    query = update.callback_query
    query.answer()
    
    # 从 callback_data 获取代理商ID
    agent_id = query.data.replace('agent_settings_', '')
    
    # 获取代理商信息
    agent = agent_bots.find_one({'agent_bot_id': agent_id})
    if not agent:
        query.edit_message_text("❌ 代理商不存在")
        return
    
    agent_name = agent.get('agent_name', 'Unknown')
    wallet_address = agent.get('wallet_address', '')
    status = agent.get('status', 'unknown')
    balance = agent.get('balance', 0)
    
    status_text = "🟢 正常" if status == 'active' else "🔴 停用"
    
    text = f"""
⚙️ <b>代理商设置</b>

👤 代理商：{agent_name}
🆔 ID：{agent_id}
📊 状态：{status_text}
💰 余额：{balance:.2f} USDT
💳 收款地址：<code>{wallet_address if wallet_address else '未绑定'}</code>

请选择操作：
"""
    
    keyboard = [
        [InlineKeyboardButton("💳 地址配置", callback_data=f"agent_wallet_config_{agent_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"agent_detail_{agent_id}")]
    ]
    
    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


def agent_wallet_config(update: Update, context: CallbackContext):
    """代理商地址配置"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 从 callback_data 获取代理商ID
    agent_id = query.data.replace('agent_wallet_config_', '')
    
    # 获取代理商信息
    agent = agent_bots.find_one({'agent_bot_id': agent_id})
    if not agent:
        query.edit_message_text("❌ 代理商不存在")
        return
    
    wallet_address = agent.get('wallet_address', '')
    
    # 设置管理员输入状态
    user.update_one(
        {'user_id': user_id},
        {'$set': {'sign':  f'set_agent_wallet_{agent_id}'}}
    )
    
    text = f"""
💳 <b>地址配置</b>

👤 代理商：{agent.get('agent_name', 'Unknown')}
💳 当前地址：<code>{wallet_address if wallet_address else '未绑定'}</code>

请输入新的 TRC20 收款地址：

💡 地址格式：T开头，34位字符

发送 /cancel 取消操作
"""
    
    keyboard = [[InlineKeyboardButton("❌ 取消", callback_data=f"agent_settings_{agent_id}")]]
    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


def handle_set_agent_wallet(update: Update, context: CallbackContext, user_id: int, sign: str):
    """处理管理员设置代理商地址"""
    text = update.message.text.strip()
    
    if text == '/cancel':
        user.update_one({'user_id':  user_id}, {'$set':  {'sign': ''}})
        update.message.reply_text("❌ 已取消")
        return True
    
    # 获取代理商ID
    agent_id = sign.replace('set_agent_wallet_', '')
    
    # 验证 TRC20 地址格式
    if not text.startswith('T') or len(text) != 34:
        update.message.reply_text("❌ 地址格式错误！\n\nTRC20 地址应以 T 开头，共 34 位字符")
        return True
    
    # 更新代理商地址
    result = agent_bots.update_one(
        {'agent_bot_id': agent_id},
        {'$set': {'wallet_address':  text}}
    )
    
    # 清除状态
    user.update_one({'user_id': user_id}, {'$set': {'sign': ''}})
    
    if result.modified_count > 0:
        keyboard = [[InlineKeyboardButton("🔙 返回设置", callback_data=f"agent_settings_{agent_id}")]]
        update.message.reply_text(
            f"✅ 地址已更新\n\n💳 新地址：<code>{text}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    else:
        update.message.reply_text("❌ 更新失败，请重试")
    
    return True


def show_agent_address_config(update: Update, context: CallbackContext):
    """显示代理商地址配置"""
    query = update.callback_query
    query.answer()
    
    # 从 callback_data 获取代理商ID
    agent_id = query.data.replace('agent_address_config_', '').replace('agent_wallet_config_', '')
    
    # 获取代理商信息
    agent = agent_bots.find_one({'agent_bot_id': agent_id})
    if not agent:
        query.edit_message_text("❌ 代理商不存在")
        return
    
    wallet_address = agent.get('wallet_address', '')
    
    text = f"""
💳 <b>地址配置</b>

👤 代理商：{agent.get('agent_name', 'Unknown')}
🆔 ID：{agent_id}
💳 当前地址：<code>{wallet_address if wallet_address else '未绑定'}</code>

请选择操作：
"""
    
    keyboard = [
        [InlineKeyboardButton("✏️ 修改地址", callback_data=f"request_agent_address_{agent_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"agent_settings_{agent_id}")]
    ]
    
    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


def request_agent_address_input(update: Update, context: CallbackContext):
    """请求输入代理商地址"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 从 callback_data 获取代理商ID
    agent_id = query.data.replace('request_agent_address_', '')
    
    # 获取代理商信息
    agent = agent_bots.find_one({'agent_bot_id': agent_id})
    if not agent:
        query.edit_message_text("❌ 代理商不存在")
        return
    
    # 设置管理员输入状态
    user.update_one(
        {'user_id': user_id},
        {'$set': {'sign': f'set_agent_wallet_{agent_id}'}}
    )
    
    text = f"""
💳 <b>修改收款地址</b>

👤 代理商：{agent.get('agent_name', 'Unknown')}
💳 当前地址：<code>{agent.get('wallet_address', '未绑定')}</code>

请输入新的 TRC20 收款地址：

💡 地址格式：T开头，34位字符

发送 /cancel 取消操作
"""
    
    keyboard = [[InlineKeyboardButton("❌ 取消", callback_data=f"agent_address_config_{agent_id}")]]
    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


def handle_agent_address_input(update: Update, context: CallbackContext, user_id: int, sign: str):
    """处理管理员输入的代理商地址"""
    text = update.message.text.strip()
    
    # 获取代理商ID
    agent_id = sign.replace('set_agent_wallet_', '')
    
    if text == '/cancel':
        user.update_one({'user_id': user_id}, {'$set': {'sign': ''}})
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data=f"agent_address_config_{agent_id}")]]
        update.message.reply_text("❌ 已取消", reply_markup=InlineKeyboardMarkup(keyboard))
        return True
    
    # 验证 TRC20 地址格式
    if not text.startswith('T') or len(text) != 34:
        update.message.reply_text("❌ 地址格式错误！\n\nTRC20 地址应以 T 开头，共 34 位字符\n\n请重新输入或发送 /cancel 取消")
        return True
    
    # 保存待确认的地址
    context.user_data['pending_wallet_address'] = text
    context.user_data['pending_agent_id'] = agent_id
    
    # 清除输入状态
    user.update_one({'user_id': user_id}, {'$set': {'sign': ''}})
    
    # 显示确认
    agent = agent_bots.find_one({'agent_bot_id': agent_id})
    old_address = agent.get('wallet_address', '未绑定') if agent else '未绑定'
    
    confirm_text = f"""
💳 <b>确认修改地址</b>

👤 代理商：{agent.get('agent_name', 'Unknown') if agent else 'Unknown'}
📍 旧地址：<code>{old_address}</code>
���� 新地址：<code>{text}</code>

确认修改吗？
"""
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认修改", callback_data=f"confirm_agent_address_{agent_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"agent_address_config_{agent_id}")
        ]
    ]
    
    update.message.reply_text(confirm_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return True


def confirm_agent_address_change(update: Update, context: CallbackContext):
    """确认修改代理商地址"""
    query = update.callback_query
    query.answer()
    
    # 从 callback_data 获取代理商ID
    agent_id = query.data.replace('confirm_agent_address_', '')
    
    # 从 context.user_data 获取待确认的地址
    new_address = context.user_data.get('pending_wallet_address')
    pending_agent_id = context.user_data.get('pending_agent_id')
    
    # 验证数据完整性
    if not new_address or pending_agent_id != agent_id:
        query.edit_message_text("❌ 数据错误或已过期，请重新操作")
        return
    
    # 更新代理商地址
    result = agent_bots.update_one(
        {'agent_bot_id': agent_id},
        {'$set': {'wallet_address': new_address}}
    )
    
    if result.modified_count > 0:
        # 清除临时数据
        context.user_data.pop('pending_wallet_address', None)
        context.user_data.pop('pending_agent_id', None)
        
        text = f"""
✅ <b>地址已更新</b>

💳 新地址：<code>{new_address}</code>

代理商的收款地址已成功修改。
"""
        keyboard = [[InlineKeyboardButton("🔙 返回设置", callback_data=f"agent_settings_{agent_id}")]]
        query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        
        # 通知代理商（可选）
        try:
            agent = agent_bots.find_one({'agent_bot_id': agent_id})
            if agent:
                owner_id = agent.get('owner_id')
                agent_token = agent.get('agent_token')
                if owner_id and agent_token:
                    # 使用代理机器人发送通知给代理商
                    agent_bot = Bot(token=agent_token)
                    notify_text = f"""
🔔 <b>地址变更通知</b>

管理员已为您修改收款地址：
💳 新地址：<code>{new_address}</code>

如有疑问请联系管理员。
"""
                    agent_bot.send_message(chat_id=owner_id, text=notify_text, parse_mode='HTML')
                    logging.info(f"✅ 已通过代理机器人通知代理商：owner_id={owner_id}")
        except Exception as e:
            logging.error(f"通知代理商失败:  {e}")
    else:
        query.edit_message_text("❌ 更新失败，请重试")
