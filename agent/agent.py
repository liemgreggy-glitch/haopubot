"""
代理Bot主程序
每个代理使用独立的Bot Token运行，拥有独立的用户数据
"""

import os
import sys
import logging
import threading
import zipfile
import time
import re
import qrcode
import pickle
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# 翻译系统
try:
    from pygtrans import Translate
    translator = Translate()
except ImportError: 
    try:
        from googletrans import Translator
        translator = Translator()
        Translate = Translator
    except: 
        class MockTranslate:
            def translate(self, text, target='en', source='auto'):
                return type('obj', (object,), {
                    'translatedText': text
                })()
        translator = MockTranslate()
        Translate = MockTranslate
# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mongo import (
    fyb,          
    fanyibao,
    agent_bots,
    agent_product_prices,
    agent_orders,
    agent_withdrawals,
    get_agent_bot_user_collection,
    get_agent_bot_topup_collection,
    get_agent_bot_gmjlu_collection,
    create_agent_user_data,
    get_agent_bot_user,
    ensure_agent_user_exists,
    update_agent_bot_user_balance,
    get_agent_stats,
    get_real_time_stock,
    hb,
    ejfl,
    fenlei,
    beijing_now_str,
    format_beijing_time,
    get_beijing_now,
    standard_num,
    sftw,
    sifatuwen
)




# 加载环境变量 - 只加载代理Bot目录下的配置文件（不读取父目录）
agent_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(agent_dir, '.env.agent'), override=True)
load_dotenv(os.path.join(agent_dir, '.env'), override=True)
# 不调用 load_dotenv() 避免读取父目录的 .env

# 导入支付系统
try:
    from agentzfxt import get_payment_system, create_topup_order
    PAYMENT_SYSTEM_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ 支付系统导入失败: {e}")
    PAYMENT_SYSTEM_AVAILABLE = False

# 导入账号检测系统
try:
    from account_detector import BatchDetector
    ACCOUNT_DETECTOR_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️ 账号检测系统导入失败: {e}")
    ACCOUNT_DETECTOR_AVAILABLE = False
# ===================== 从 .env 读取代理配置 =====================
# 全局变量
AGENT_BOT_ID = os.getenv('AGENT_BOT_ID', '')
AGENT_BOT_TOKEN = os.getenv('AGENT_BOT_TOKEN', '')
AGENT_NAME = os.getenv('AGENT_NAME', '代理商店')
AGENT_USERNAME = os.getenv('AGENT_USERNAME', 'agent_bot')
COMMISSION_RATE = float(os.getenv('AGENT_COMMISSION_RATE', '0.25'))  # 默认25%佣金
CUSTOMER_SERVICE = os.getenv('AGENT_CUSTOMER_SERVICE', '@support')
NOTIFY_CHANNEL_ID = os.getenv('NOTIFY_CHANNEL_ID', '0')  # 通知频道ID
# 管理员ID列表 - 安全处理空字符串情况
admin_ids_str = os.getenv('ADMIN_IDS', '').strip()
ADMIN_IDS = list(map(int, filter(None, admin_ids_str.split(',')))) if admin_ids_str else []
AGENT_INFO = None

# UI配置
BANNER_IMAGE_URL = os.getenv('BANNER_IMAGE_URL', '')
BOT_NAME = os.getenv('BOT_NAME', '') or AGENT_NAME
BOT_SLOGAN = os.getenv('BOT_SLOGAN', '')
PERMANENT_USERNAME = os.getenv('PERMANENT_USERNAME', '')
NOTIFICATION_GROUP = os.getenv('NOTIFICATION_GROUP', '')
PURCHASE_NOTICE = os.getenv('PURCHASE_NOTICE', '')
PURCHASE_NOTICE_EN = os.getenv('PURCHASE_NOTICE_EN', '')

# 私信广播配置
BROADCAST_DELAY = float(os.getenv('BROADCAST_DELAY', '0.05'))  # 群发消息间隔（秒），防止限流
AGENT_ORDER_NOTIFY_GROUP = os.getenv('AGENT_ORDER_NOTIFY_GROUP', '')

# 文件路径配置
BASE_PROTOCOL_PATH = os.getenv('BASE_PROTOCOL_PATH', '/www/haopubot/haopu-main/协议号')
FALLBACK_PROTOCOL_PATH = os.getenv('FALLBACK_PROTOCOL_PATH', './协议号')

# 账号检测配置
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
BAD_ACCOUNT_GROUP_ID = os.getenv('BAD_ACCOUNT_GROUP_ID', '')
ENABLE_ACCOUNT_DETECTION = os.getenv('ENABLE_ACCOUNT_DETECTION', 'true').lower() == 'true'

# 日志配置
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/agent_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def get_fy(fstext):
    """翻译中文到英文，带缓存"""
    try:
        fy_list = fyb.find_one({'text': fstext})
        if fy_list is None:
            try:
                if hasattr(translator, 'translate'):
                    result = translator.translate(fstext.replace("\n", "\\n"), target='en')
                    if hasattr(result, 'translatedText'):
                        trans_text = result.translatedText
                    elif hasattr(result, 'text'):
                        trans_text = result.text
                    else: 
                        trans_text = str(result)
                else:
                    client = Translate(target='en', domain='com')
                    result = client.translate(fstext.replace("\n", "\\n"))
                    trans_text = result.translatedText
                
                fanyibao('英文', fstext, trans_text.replace("\\n", "\n"))
                return trans_text.replace("\\n", "\n")
            except Exception as e:
                logging.error(f"翻译失败: {e}")
                return fstext
        else:
            return fy_list['fanyi']
    except Exception as e:
        logging.error(f"获取翻译失败: {e}")
        return fstext

def t(text, lang):
    """根据语言翻译文本，中文返回原文，英文调用翻译"""
    if lang == 'zh' or not text:
        return text
    return get_fy(text)

def get_user_lang(user_id):
    """获取用户语言设置"""
    agent_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
    return agent_user.get('lang', 'zh') if agent_user else 'zh'
    
def init_agent_bot():
    """初始化代理Bot - 从环境变量读取配置"""
    global AGENT_INFO
    
    # 验证必需的环境变量
    if not AGENT_BOT_ID:
        logging.error("❌ 未设置 AGENT_BOT_ID 环境变量")
        sys.exit(1)
    
    if not AGENT_BOT_TOKEN:
        logging.error("❌ 未设置 AGENT_BOT_TOKEN 环境变量")
        sys.exit(1)
    
    # 从数据库加载代理信息（可选，用于统计）
    AGENT_INFO = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    
    if AGENT_INFO:
        # 如果数据库中有记录，检查状态
        if AGENT_INFO.get('status') != 'active':
            logging.warning(f"⚠️ 代理Bot在数据库中状态为: {AGENT_INFO.get('status')}")
        logging.info(f"✅ 从数据库加载代理信息: {AGENT_INFO.get('agent_name')}")
    else:
        # 数据库中没有记录，使用环境变量配置运行
        logging.info(f"✅ 使用环境变量配置运行")
        AGENT_INFO = {
            'agent_bot_id': AGENT_BOT_ID,
            'agent_name': AGENT_NAME,
            'agent_username': AGENT_USERNAME,
            'commission_rate': COMMISSION_RATE * 100,
            'settings': {
                'customer_service': CUSTOMER_SERVICE
            }
        }
    
    logging.info(f"   代理名称: {AGENT_NAME}")
    logging.info(f"   Bot用户名: @{AGENT_USERNAME}")
    logging.info(f"   佣金比例: {COMMISSION_RATE*100}%")
    logging.info(f"   客服联系: {CUSTOMER_SERVICE}")
    
    # 日志显示管理员配置
    if ADMIN_IDS:
        logging.info(f"   管理员ID: {ADMIN_IDS}")
        logging.info(f"   管理员数量: {len(ADMIN_IDS)}")
    else:
        logging.warning(f"   ⚠️ 未配置管理员ID (ADMIN_IDS)")
        logging.warning(f"   ⚠️ 请在 .env.agent 或 .env 文件中设置 ADMIN_IDS 环境变量")
        logging.warning(f"   ⚠️ 例如: ADMIN_IDS=1681704945")
    
    # 自动同步通知频道ID到数据库
    sync_notify_channel_to_db()


def sync_notify_channel_to_db():
    """将代理的 NOTIFY_CHANNEL_ID 同步到数据库"""
    try:
        # 安全处理字符串转换
        if isinstance(NOTIFY_CHANNEL_ID, str):
            notify_channel_id_str = NOTIFY_CHANNEL_ID.strip()
        else:
            notify_channel_id_str = str(NOTIFY_CHANNEL_ID)
        
        # 尝试转换为整数
        try:
            notify_channel_id = int(notify_channel_id_str)
        except ValueError:
            notify_channel_id = 0
        
        if AGENT_BOT_ID and notify_channel_id != 0:
            result = agent_bots.update_one(
                {'agent_bot_id': AGENT_BOT_ID},
                {'$set': {'notify_channel_id': notify_channel_id}}
            )
            if result.modified_count > 0:
                logging.info(f"✅ 已同步通知频道ID到数据库: {notify_channel_id}")
            else:
                logging.info(f"ℹ️ 通知频道ID无需更新: {notify_channel_id}")
        else:
            if not AGENT_BOT_ID:
                logging.warning("⚠️ AGENT_BOT_ID 未设置，无法同步通知频道")
            if notify_channel_id == 0:
                logging.warning("⚠️ NOTIFY_CHANNEL_ID 未设置，跳过同步")
    except Exception as e:
        logging.error(f"❌ 同步通知频道ID失败: {e}")


# ===================== 管理员验证函数 =====================

def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    is_authorized = user_id in ADMIN_IDS
    if not is_authorized:
        logging.info(f"⚠️ 用户 {user_id} 尝试访问管理面板但不在管理员列表中")
        logging.info(f"   当前配置的管理员ID: {ADMIN_IDS}")
    return is_authorized


def require_admin(func):
    """装饰器：要求管理员权限"""
    def wrapper(update: Update, context: CallbackContext):
        user_id = update.effective_user.id if update.effective_user else 0
        if not is_admin(user_id):
            error_msg = "❌ 无权限访问"
            if not ADMIN_IDS:
                error_msg += "\n\n⚠️ 系统未配置管理员\n请联系系统管理员在配置文件中添加 ADMIN_IDS"
            else:
                error_msg += f"\n\n您的ID: {user_id}\n请联系系统管理员添加到管理员列表"
            
            if update.callback_query:
                update.callback_query.answer("❌ 无权限访问", show_alert=True)
            elif update.message:
                update.message.reply_text(error_msg)
            return
        return func(update, context)
    return wrapper


def get_time_greeting(lang='zh'):
    """根据北京时间返回问候语"""
    beijing_time = get_beijing_now()
    hour = beijing_time.hour
    
    if lang == 'zh':
        if 6 <= hour < 12:
            return "早上好"
        elif 12 <= hour < 18:
            return "下午好"
        elif 18 <= hour < 24:
            return "晚上好"
        else:  # 0 <= hour < 6
            return "凌晨好"
    else:
        if 6 <= hour < 12:
            return "Good morning"
        elif 12 <= hour < 18:
            return "Good afternoon"
        elif 18 <= hour < 24:
            return "Good evening"
        else:  # 0 <= hour < 6
            return "Hello"


def send_order_notify_to_group(order_type, order_data, bot=None):
    """
    发送订单通知到群组
    
    Args:
        order_type: 订单类型 'purchase' 或 'recharge'
        order_data: 订单详情字典
        bot: 可选的Bot实例，如果不提供则创建新实例
    """
    # 检查是否配置了通知群
    if not AGENT_ORDER_NOTIFY_GROUP or AGENT_ORDER_NOTIFY_GROUP.strip() == '':
        return
    
    try:
        # 转换群ID为整数
        group_id = int(AGENT_ORDER_NOTIFY_GROUP)
        
        # 如果没有提供bot实例，则创建一个
        if bot is None:
            from telegram import Bot
            bot = Bot(token=AGENT_BOT_TOKEN)
        
        if order_type == 'purchase':
            # 购买订单通知
            username_display = f"@{order_data['username']}" if order_data['username'] and order_data['username'] != 'unknown' else f"{order_data['user_id']}"
            
            # 先提取变量避免f-string语法问题
            order_id = order_data['order_id']
            order_time = order_data['order_time']
            user_id = order_data['user_id']
            category = order_data['category']
            product_name = order_data['product_name']
            quantity = order_data['quantity']
            total_price = order_data['total_price']
            hq_total_price = order_data['hq_total_price']
            agent_price = order_data['agent_price']
            profit = order_data['profit']
            profit_per_unit = order_data['profit_per_unit']
            old_balance = order_data['old_balance']
            new_balance = order_data['new_balance']
            total_spent = order_data['total_spent']
            total_orders = order_data['total_orders']
            
            message = f"""🛒 <b>收到了一份 采购订单</b> 📦

<b>👤 用户名: </b> <b>{username_display}</b>
<b>💎 利润加价:</b> <b>{profit_per_unit:.2f}U</b>
<b>🧾 订单号:</b> <code>{order_id}</code>
━━━━━━━━━━━━━━━━━━
<b>📅 日期|时间:</b> <b>{order_time}</b>
<b>👤 来自用户:</b> <b>{user_id}</b>
<b>🏷 分类:</b> <b>{category}</b>
<b>📦 商品:</b> <b>{product_name}</b>
<b>✅ 购买数量:</b> <b>{quantity}</b>
<b>💰 订单总价值:</b> <b>{total_price:.2f}U</b>
<b>💵 总部原价:</b> <b>{hq_total_price:.2f}U</b>
<b>💲 单价（代理）:</b> <b>{agent_price:.2f}U</b>
<b>💎 本单利润:</b> <b>{profit:.2f}U</b>
<b>💰 用户旧余额:</b> <b>{old_balance:.2f}U</b>
<b>💰 用户当前余额: </b> <b>{new_balance:.2f}U</b>
<b>📊 累计消费:</b> <b>{total_spent:.2f}U (共 {total_orders} 单)</b>
━━━━━━━━━━━━━━━━━━
<b>✅ 您从这笔交易中获得的利润({quantity} * {profit_per_unit:.2f}U):</b> <b>{profit:.2f}</b>"""
            
        elif order_type == 'recharge':
            # 充值订单通知
            username_display = f"@{order_data['username']}" if order_data['username'] and order_data['username'] != 'unknown' else f"{order_data['user_id']}"
            
            # 先提取变量避免f-string语法问题
            order_id = order_data['order_id']
            order_time = order_data['order_time']
            user_id = order_data['user_id']
            amount = float(order_data.get('amount', 0))
            old_balance = float(order_data.get('old_balance', 0))
            new_balance = float(order_data.get('new_balance', 0))
            total_recharge = float(order_data.get('total_recharge', 0))
            total_recharge = float(order_data.get('total_recharge', 0))
            deposit_address = os.getenv('AGENT_DEPOSIT_ADDRESS', '')
            
            message = f"""💰 <b>收到了一份 充值订单</b> 💵

<b>👤 用户名: </b> <b>{username_display}</b>
<b>🧾 充值单号:</b> <code>{order_id}</code>
━━━━━━━━━━━━━━━━━━
<b>📅 日期|时间:</b> <b>{order_time}</b>
<b>👤 来自用户:</b> <b>{user_id}</b>
<b>💵 充值金额:</b> <b>{amount:.2f} USDT</b>
<b>💰 用户旧余额:</b> <b>{old_balance:.2f} U</b>
<b>💰 用户当前余额:</b> <b>{new_balance:.2f} U</b>
<b>📊 累计充值:</b> <b>{total_recharge:.2f} U</b>
<b>🏦 收款地址:</b>
<code>{deposit_address}</code>
━━━━━━━━━━━━━━━━━━"""

            # 创建查看交易按钮
            keyboard = [[InlineKeyboardButton("【查看交易】", url=f"https://tronscan.org/#/address/{deposit_address}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
        else:
            logging.warning(f"⚠️ 未知的订单类型: {order_type}")
            return
        
        # 发送消息到群组
        if order_type == 'recharge':
            bot.send_message(
                chat_id=group_id,
                text=message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            bot.send_message(
                chat_id=group_id,
                text=message,
                parse_mode='HTML'
            )
        logging.info(f"✅ 订单通知已发送到群组: {group_id}, 类型: {order_type}")
        
    except ValueError as e:
        logging.error(f"❌ 群组ID格式错误: {AGENT_ORDER_NOTIFY_GROUP}, 错误: {e}")
    except Exception as e:
        logging.error(f"❌ 发送订单通知到群组失败: {e}")


def send_media_message(context, chat_id, media_url, caption, parse_mode, reply_markup):
    """
    根据URL后缀自动判断并发送对应类型的媒体消息
    支持：图片(.jpg/.png/.webp)、GIF(.gif)、视频(.mp4)
    """
    if not media_url:
        # 没有媒体URL，发送纯文本消息
        context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return
    
    # 获取URL的小写后缀
    url_lower = media_url.lower()
    
    try:
        if url_lower.endswith(('.jpg', '.jpeg', '.png', '.webp')):
            # 图片
            context.bot.send_photo(
                chat_id=chat_id,
                photo=media_url,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        elif url_lower.endswith('.gif'):
            # GIF动画
            context.bot.send_animation(
                chat_id=chat_id,
                animation=media_url,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        elif url_lower.endswith('.mp4'):
            # 视频
            context.bot.send_video(
                chat_id=chat_id,
                video=media_url,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        else:
            # 未知格式，发送纯文本
            logging.warning(f"未识别的媒体格式: {media_url}")
            context.bot.send_message(
                chat_id=chat_id,
                text=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
    except Exception as e:
        logging.error(f"发送媒体消息失败: {e}")
        # 发送失败，fallback到纯文本
        context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )


# ===================== 国家/区号映射表 =====================

COUNTRY_MAP = {
    "英国": "+44",
    "美国": "+1",
    "日本": "+81",
    "韩国": "+82",
    "中国": "+86",
    "香港": "+852",
    "台湾": "+886",
    "新加坡": "+65",
    "马来西亚": "+60",
    "泰国": "+66",
    "越南": "+84",
    "印度": "+91",
    "印尼": "+62",
    "菲律宾": "+63",
    "澳大利亚": "+61",
    "加拿大": "+1",
    "法国": "+33",
    "德国": "+49",
    "意大利": "+39",
    "西班牙": "+34",
    "俄罗斯": "+7",
    "巴西": "+55",
    "墨西哥": "+52",
    "阿根廷": "+54",
    "土耳其": "+90",
    "沙特": "+966",
    "阿联酋": "+971",
    "埃及": "+20",
    "南非": "+27",
    "尼日利亚": "+234",
    "波兰": "+48",
    "荷兰": "+31",
    "比利时": "+32",
    "瑞士": "+41",
    "奥地利": "+43",
    "瑞典": "+46",
    "挪威": "+47",
    "丹麦": "+45",
    "芬兰": "+358",
    "葡萄牙": "+351",
    "希腊": "+30",
    "捷克": "+420",
    "匈牙利": "+36",
    "罗马尼亚": "+40",
    "乌克兰": "+380",
    "以色列": "+972",
    "巴基斯坦": "+92",
    "孟加拉": "+880",
    "缅甸": "+95",
    "柬埔寨": "+855",
    "老挝": "+856",
    "新西兰": "+64",
}


# ===================== 主要功能处理器 =====================


def show_product_detail_from_start(update: Update, context: CallbackContext, user_id: int, nowuid: str):
    """
    从/start命令显示商品详情页面
    用于处理 /start buy_{nowuid} 参数
    """
    # 获取商品信息
    product = ejfl.find_one({'nowuid': nowuid})
    if not product:
        update.message.reply_text("❌ 商品不存在或已下架")
        return
    
    product_name = product.get('projectname', '未知商品')
    hq_price = float(product.get('money', 0))
    
    # 计算代理价格
    agent_price = hq_price * (1 + COMMISSION_RATE)
    
    # 获取库存
    stock = get_real_time_stock(nowuid)
    
    # 获取分类
    uid = product.get('uid')
    category = fenlei.find_one({'uid': uid})
    category_name = category.get('projectname', '未知分类') if category else '未知分类'
    
    text = f"""
✅ 您正在购买：{product_name}

💲 价格：{agent_price:.2f} USDT

📦 库存：{stock} 件

⚠️ 未使用过本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！

⚠️ 账号价格会根据市场价有所浮动！请理解！
    """.strip()
    
    keyboard = []
    
    if stock > 0:
        keyboard.append([
            InlineKeyboardButton("✅ 购买", callback_data=f"buy_{nowuid}"),
            InlineKeyboardButton("📚 使用说明", callback_data=f"usage_{nowuid}")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("❌ 已售罄", callback_data="out_of_stock")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🏠 主菜单", callback_data="back_to_main"),
        InlineKeyboardButton("🔙 返回列表", callback_data=f"category_{uid}")
    ])
    
    context.bot.send_message(
        chat_id=user_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def start(update: Update, context: CallbackContext):
    """处理/start命令"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    fullname = update.effective_user.full_name.replace('<', '').replace('>', '')
    
    # 确保用户存在于代理数据库
    exists, agent_user = ensure_agent_user_exists(AGENT_BOT_ID, user_id, username, fullname)
    
    if not exists or not agent_user: 
        update.message.reply_text("❌ System error, please contact support")
        return
    
    # 获取用户语言
    lang = agent_user.get('lang', 'zh')
    
    # 处理 buy_ 参数，跳转到购买页面
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith('buy_'):
            nowuid = arg[4:]  # 提取 nowuid
            # 调用购买商品的逻辑，显示该商品的购买页面
            show_product_detail_from_start(update, context, user_id, nowuid)
            return
    
    # 获取用户信息
    balance = agent_user.get('USDT', 0)
    total_purchases = agent_user.get('zgsl', 0)
    creation_time = agent_user.get('creation_time', '')
    
    # 截取日期部分
    registration_date = creation_time[:10] if creation_time else ('Unknown' if lang != 'zh' else '未知')
    
    # 获取问候语
    greeting = get_time_greeting(lang)
    
    # 构建欢迎消息
    welcome_text = ""
    
    # 如果配置了Bot名称和标语，显示它们
    if BOT_NAME or BOT_SLOGAN: 
        if BOT_NAME:
            welcome_text += f"          <b>{BOT_NAME}</b>\n"
        if BOT_SLOGAN: 
            welcome_text += f"   {BOT_SLOGAN}\n"
        welcome_text += "\n"
    
    # 问候和用户信息
    if lang == 'zh':
        welcome_text += f"👋 {greeting}，{fullname}\n\n"
        welcome_text += f"🆔 <b>用户ID：<code>{user_id}</code></b>\n"
        welcome_text += f"📅 <b>注册时间：{registration_date}</b>\n\n"
        welcome_text += f"💰 <b>账户余额：{balance:.2f}</b>\n"
        welcome_text += f"✅ <b>总购买数量：{total_purchases}\n</b>"
    else:
        welcome_text += f"👋 {greeting}, {fullname}\n\n"
        welcome_text += f"🆔 <b>User ID:  <code>{user_id}</code></b>\n"
        welcome_text += f"📅 <b>Registered:  {registration_date}</b>\n\n"
        welcome_text += f"💰 <b>Balance: {balance:.2f}</b>\n"
        welcome_text += f"✅ <b>Total Purchases: {total_purchases}\n</b>"
    
    # 分隔线
    welcome_text += "\n" + "➖" * 10 + "\n"
    
    # 永久用户名和通知群
    if PERMANENT_USERNAME: 
        if lang == 'zh':
            welcome_text += f"👤 <b>永久用户名：{PERMANENT_USERNAME}</b>\n"
        else: 
            welcome_text += f"👤 <b>Permanent Username: {PERMANENT_USERNAME}</b>\n"
    if NOTIFICATION_GROUP: 
        if lang == 'zh':
            welcome_text += f"📢 <b>补货通知群：{NOTIFICATION_GROUP}</b>\n"
        else:
            welcome_text += f"📢 <b>Notification Group:  {NOTIFICATION_GROUP}</b>\n"
    
    # 2列网格按钮布局
    if lang == 'zh':
        keyboard = [
            [
                InlineKeyboardButton("📋 账号列表", callback_data="product_list"),
                InlineKeyboardButton("💰 充值余额", callback_data="recharge")
            ],
            [
                InlineKeyboardButton("📖 购买须知", callback_data="purchase_notice"),
                InlineKeyboardButton("📝 购买记录", callback_data="purchase_history")
            ],
            [
                InlineKeyboardButton("🌍 区号搜索", callback_data="country_search"),
                InlineKeyboardButton("🌐 My Language", callback_data="switch_lang")
            ]
        ]
    else: 
        keyboard = [
            [
                InlineKeyboardButton("📋 Account List", callback_data="product_list"),
                InlineKeyboardButton("💰 Recharge", callback_data="recharge")
            ],
            [
                InlineKeyboardButton("📖 Purchase Notice", callback_data="purchase_notice"),
                InlineKeyboardButton("📝 Purchase History", callback_data="purchase_history")
            ],
            [
                InlineKeyboardButton("🌍 Country Search", callback_data="country_search"),
                InlineKeyboardButton("🌐 My Language", callback_data="switch_lang")
            ]
        ]
    
    # 使用新的媒体发送函数，自动检测媒体类型
    send_media_message(
        context=context,
        chat_id=user_id,
        media_url=BANNER_IMAGE_URL,
        caption=welcome_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def show_product_list(update:  Update, context: CallbackContext):
    """显示商品分类列表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取用户语言
    agent_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
    lang = agent_user.get('lang', 'zh') if agent_user else 'zh'
    
    # 获取所有一级分类
    categories = list(fenlei.find({}).sort('row', 1))
    
    if not categories:
        query.edit_message_text(t("暂无商品分类", lang))
        return
    
    if lang == 'zh':
        text = """🛒 <b>商品分类</b> - 请选择所需：

❗ 首次购买请先少量测试，避免纠纷！

❗ 长期未使用账户可能会出现问题，联系客服处理"""
    else:
        text = """🛒 <b>Product Categories</b> - Please select: 

❗ Please test with small quantity for first purchase! 

❗ Long unused accounts may have issues, contact support"""
    
    keyboard = []
    for category in categories: 
        uid = category.get('uid')
        category_name = category.get('projectname', '未知分类')
        
        # 获取该分类下的所有商品
        products = list(ejfl.find({'uid': uid}))
        
        # 统计该分类下所有商品的总库存数量
        total_stock = sum(get_real_time_stock(product.get('nowuid')) for product in products if product.get('nowuid'))
        
        if total_stock > 0:
            # 翻译分类名称
            display_name = t(category_name, lang) if lang != 'zh' else category_name
            keyboard.append([
                InlineKeyboardButton(
                    f"{display_name} ({total_stock})",
                    callback_data=f"category_{uid}"
                )
            ])
    
    back_text = "🔙 返回主菜单" if lang == 'zh' else "🔙 Back to Main"
    keyboard.append([InlineKeyboardButton(back_text, callback_data="back_to_main")])
    
    # 删除原消息并发送新消息（兼容图片消息）
    try:
        query.message.delete()
    except Exception as e:
        logging.debug(f"删除消息失败（预期行为）: {e}")
    context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_category_products(update: Update, context: CallbackContext):
    """显示分类下的商品列表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取用户语言
    agent_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
    lang = agent_user.get('lang', 'zh') if agent_user else 'zh'
    
    # 从callback_data中提取分类uid
    category_uid = query.data.replace("category_", "")
    
    # 获取分类信息
    category = fenlei.find_one({'uid': category_uid})
    if not category:
        query.edit_message_text(t("分类不存在", lang))
        return
    
    category_name = category.get('projectname', '未知分类')
    display_category = t(category_name, lang) if lang != 'zh' else category_name
    
    # 获取该分类下的所有商品
    products = list(ejfl.find({'uid': category_uid}).sort('row', 1))
    
    if not products:
        msg = f"{display_category} 暂无商品" if lang == 'zh' else f"No products in {display_category}"
        query.edit_message_text(msg)
        return
    
    if lang == 'zh':
        text = f"""📦 <b>{category_name} 请选择商品：</b>

❗️有密码的账户售后时间1小时内，二级未知的账户售后30分钟内！

❗️购买后请第一时间检查账户，提供证明处理售后 超时损失自付！"""
    else:
        text = f"""📦 <b>{display_category} - Select product:</b>

❗️Accounts with password:  1 hour after-sales. Unknown 2FA:  30 minutes! 

❗️Please check account immediately after purchase. Provide proof for after-sales. Timeout at your own risk!"""
    
    keyboard = []
    for product in products:
        nowuid = product.get('nowuid')
        product_name = product.get('projectname', '未知商品')
        hq_price = float(product.get('money', 0))
        
        # 计算代理价格
        agent_price = hq_price * (1 + COMMISSION_RATE)
        
        # 获取库存
        stock = get_real_time_stock(nowuid)
        
        # 显示商品
        if stock > 0:
            display_product = t(product_name, lang) if lang != 'zh' else product_name
            keyboard.append([
                InlineKeyboardButton(
                    f"{display_product} - {agent_price:.2f}U [{stock}]",
                    callback_data=f"product_{nowuid}"
                )
            ])
    
    back_text = "🔙 返回分类" if lang == 'zh' else "🔙 Back"
    keyboard.append([InlineKeyboardButton(back_text, callback_data="product_list")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_product_detail(update: Update, context:  CallbackContext):
    """显示商品详情"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取用户语言
    agent_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
    lang = agent_user.get('lang', 'zh') if agent_user else 'zh'
    
    # 从callback_data中提取商品nowuid
    nowuid = query.data.replace("product_", "")
    
    # 获取商品信息
    product = ejfl.find_one({'nowuid': nowuid})
    if not product:
        query.edit_message_text(t("商品不存在", lang))
        return
    
    product_name = product.get('projectname', '未知商品')
    hq_price = float(product.get('money', 0))
    desc = product.get('text', '暂无说明')
    
    # 计算代理价格
    agent_price = hq_price * (1 + COMMISSION_RATE)
    
    # 获取库存
    stock = get_real_time_stock(nowuid)
    
    # 获取分类
    uid = product.get('uid')
    category = fenlei.find_one({'uid': uid})
    category_name = category.get('projectname', '未知分类') if category else '未知分类'
    
    # 翻译商品名
    display_product = t(product_name, lang) if lang != 'zh' else product_name
    
    if lang == 'zh': 
        text = f"""
✅ 您正在购买：{product_name}

💲 价格：{agent_price:.2f} USDT

📦 库存：{stock} 件

⚠️ 未使用过本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！

⚠️ 账号价格会根据市场价有所浮动！请理解！
        """.strip()
    else:
        text = f"""
✅ You are purchasing:  {display_product}

💲 Price: {agent_price:.2f} USDT

📦 Stock: {stock} pcs

⚠️ If new to our products, please test with small quantity first to avoid disputes! 

⚠️ Prices may fluctuate based on market! 
        """.strip()
    
    keyboard = []
    
    if stock > 0:
        if lang == 'zh':
            keyboard.append([
                InlineKeyboardButton("✅ 购买", callback_data=f"buy_{nowuid}"),
                InlineKeyboardButton("📚 使用说明", callback_data=f"usage_{nowuid}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("✅ Buy", callback_data=f"buy_{nowuid}"),
                InlineKeyboardButton("📚 Instructions", callback_data=f"usage_{nowuid}")
            ])
    else:
        if lang == 'zh':
            keyboard.append([
                InlineKeyboardButton("❌ 已售罄", callback_data="out_of_stock")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("❌ Sold Out", callback_data="out_of_stock")
            ])
    
    if lang == 'zh':
        keyboard.append([
            InlineKeyboardButton("🏠 主菜单", callback_data="back_to_main"),
            InlineKeyboardButton("🔙 返回列表", callback_data=f"category_{uid}")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main"),
            InlineKeyboardButton("🔙 Back", callback_data=f"category_{uid}")
        ])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def buy_product(update:  Update, context: CallbackContext):
    """购买商品 - 提示输入数量"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 从callback_data中提取商品nowuid
    nowuid = query.data.replace("buy_", "")
    
    # 获取商品信息
    product = ejfl.find_one({'nowuid': nowuid})
    if not product:
        query.answer(t("商品不存在", 'zh'), show_alert=True)
        return
    
    # 检查库存
    stock = get_real_time_stock(nowuid)
    if stock <= 0:
        query.answer("❌ Out of stock" if get_user_lang(user_id) != 'zh' else "❌ 库存不足", show_alert=True)
        return
    
    # 获取用户余额
    agent_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
    if not agent_user:
        query.answer("User not found" if get_user_lang(user_id) != 'zh' else "用户不存在", show_alert=True)
        return
    
    lang = agent_user.get('lang', 'zh')
    balance = agent_user.get('USDT', 0)
    hq_price = float(product.get('money', 0))
    agent_price = hq_price * (1 + COMMISSION_RATE)
    
    # 检查最低余额
    if balance < agent_price:
        msg = "❌ Insufficient balance, please recharge" if lang != 'zh' else "❌ 余额不足，请立即充值"
        query.answer(msg, show_alert=True)
        return
    
    # 删除当前消息
    try:
        query.delete_message()
    except Exception as e: 
        logging.warning(f"删除消息失败: {e}")
    
    # 设置用户状态为等待输入数量
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    agent_users.update_one(
        {'user_id': user_id},
        {'$set': {'sign': f"gmqq {nowuid}:{stock}"}}
    )
    
    # 发送提示消息
    if lang == 'zh':
        text = f"""
<b>请输入数量：
格式：</b><code>10</code>
        """.strip()
    else:
        text = f"""
<b>Please enter quantity:
Format:</b> <code>10</code>
        """.strip()
    
    context.bot.send_message(
        chat_id=user_id,
        text=text,
        parse_mode='HTML'
    )

def show_usage_instruction(update:  Update, context: CallbackContext):
    """显示商品使用说明"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 从callback_data中提取商品nowuid
    nowuid = query.data.replace("usage_", "")
    
    # 获取商品信息
    product = ejfl.find_one({'nowuid': nowuid})
    if not product:
        msg = "Product not found" if lang != 'zh' else "商品不存在"
        query.answer(msg, show_alert=True)
        return
    
    # 获取使用说明
    sysm = product.get('sysm', '暂无说明' if lang == 'zh' else 'No instructions')
    
    # 翻译使用说明
    display_sysm = t(sysm, lang) if lang != 'zh' else sysm
    
    close_text = "❌ 关闭" if lang == 'zh' else "❌ Close"
    keyboard = [
        [InlineKeyboardButton(close_text, callback_data=f"close_{user_id}")]
    ]
    
    context.bot.send_message(
        chat_id=user_id,
        text=display_sysm,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def handle_quantity_input(update: Update, context: CallbackContext):
    """处理用户输入的购买数量或提现地址或搜索关键词"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 检查是否在等待代理私信图文输入
    if context.user_data.get(f'agent_waiting_tuwen{user_id}'):
        # 验证是否为管理员
        if not is_admin(user_id):
            return
        
        # 删除等待标记
        del context.user_data[f'agent_waiting_tuwen{user_id}']
        
        # 处理图文内容
        if update.message.photo:
            # 图片+文字
            r_text = update.message.caption if update.message.caption else ''
            file = update.message.photo[-1].file_id
            sftw.update_one(
                {'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'}, 
                {'$set': {'text': r_text, 'file_id': file, 'send_type': 'photo', 'state': 1}}
            )
            message_id = context.bot.send_message(chat_id=user_id, text='✅ 图文设置成功（图片）')
        elif update.message.animation:
            # 动画+文字
            r_text = update.message.caption if update.message.caption else ''
            file = update.message.animation.file_id
            sftw.update_one(
                {'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'}, 
                {'$set': {'text': r_text, 'file_id': file, 'send_type': 'animation', 'state': 1}}
            )
            message_id = context.bot.send_message(chat_id=user_id, text='✅ 图文设置成功（动画）')
        else:
            # 纯文字
            r_text = text
            sftw.update_one(
                {'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'}, 
                {'$set': {'text': r_text, 'file_id': '', 'send_type': 'text', 'state': 1}}
            )
            message_id = context.bot.send_message(chat_id=user_id, text='✅ 图文设置成功（文字）')
        
        time.sleep(3)
        try:
            context.bot.delete_message(chat_id=user_id, message_id=message_id.message_id)
        except:
            pass
        
        # 删除提示消息
        wanfa_msg_id = context.user_data.get(f'agent_wanfapeizhi{user_id}')
        if wanfa_msg_id:
            try:
                context.bot.delete_message(chat_id=user_id, message_id=wanfa_msg_id.message_id)
            except:
                pass
            del context.user_data[f'agent_wanfapeizhi{user_id}']
        
        return
    
    # 检查是否在等待代理私信按钮输入
    if context.user_data.get(f'agent_waiting_anniu{user_id}'):
        # 验证是否为管理员
        if not is_admin(user_id):
            return
        
        # 删除等待标记
        del context.user_data[f'agent_waiting_anniu{user_id}']
        
        # 处理按钮设置
        keyboard = parse_urls(text)
        dumped = pickle.dumps(keyboard)
        sftw.update_one(
            {'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'}, 
            {'$set': {'keyboard': dumped, 'key_text': text}}
        )
        
        try:
            message_id = context.bot.send_message(
                chat_id=user_id, 
                text='✅ 按钮设置成功',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            time.sleep(10)
            context.bot.delete_message(chat_id=user_id, message_id=message_id.message_id)
        except:
            message_id = context.bot.send_message(chat_id=user_id, text='✅ 按钮设置成功')
            time.sleep(3)
            context.bot.delete_message(chat_id=user_id, message_id=message_id.message_id)
        
        # 删除提示消息
        wanfa_msg_id = context.user_data.get(f'agent_wanfapeizhi{user_id}')
        if wanfa_msg_id:
            try:
                context.bot.delete_message(chat_id=user_id, message_id=wanfa_msg_id.message_id)
            except:
                pass
            del context.user_data[f'agent_wanfapeizhi{user_id}']
        
        return
    
    # 检查是否在等待提现地址输入（地址绑定）
    if context.user_data.get('waiting_for_withdraw_address'):
        # 验证是否为管理员
        if not is_admin(user_id):
            return
        
        # 简单验证地址格式（TRC20地址通常以T开头，34个字符）
        if not text.startswith('T') or len(text) != 34:
            update.message.reply_text(
                "❌ 地址格式不正确，请输入正确的TRC20地址\n"
                "TRC20地址应以T开头，共34个字符\n"
                "⚠️ 请仔细核对地址，避免资金损失"
            )
            return
        
        # 检查是地址绑定还是提现确认
        if context.user_data.get('withdraw_address_binding'):
            # 地址绑定流程
            handle_address_binding(update, context, text)
        else:
            # 兼容旧版提现流程（已弃用，将在未来版本移除）
            # TODO: 此代码路径在下一个主要版本中将被移除
            confirm_withdraw(update, context, text)
        return
    
    # 检查是否在等待提现金额输入
    if context.user_data.get('waiting_for_withdraw_amount'):
        # 验证是否为管理员
        if not is_admin(user_id):
            return
        
        handle_withdraw_amount_input(update, context, text)
        return
    
    # 获取用户信息
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    agent_user = agent_users.find_one({'user_id': user_id})
    
    if not agent_user: 
        return
    
    sign = agent_user.get('sign', '')
    
    # 检查是否在自定义充值金额输入流程中
    if sign == 'recharge_custom_amount': 
        handle_custom_amount_input(update, context, user_id, text)
        return
    
    # 检查是否在国家搜索流程中
    if sign == 'country_search':
        handle_country_search_input(update, context, user_id, text)
        return
    
    # 检查是否在购买流程中
    if not sign or not sign.startswith('gmqq '):
        return
    
    # 解析sign: "gmqq {nowuid}:{max_stock}"
    try:
        parts = sign.replace('gmqq ', '').split(':')
        nowuid = parts[0]
        max_stock = int(parts[1])
    except (ValueError, IndexError) as e:
        logging.warning(f"解析购买状态失败: {e}")
        msg = "❌ Status error, please try again" if lang != 'zh' else "❌ 状态错误，请重新购买"
        update.message.reply_text(msg)
        agent_users.update_one({'user_id': user_id}, {'$set': {'sign': '0'}})
        return
    
    # 获取商品信息
    product = ejfl.find_one({'nowuid': nowuid})
    if not product:
        msg = "❌ Product not found" if lang != 'zh' else "❌ 商品不存在"
        update.message.reply_text(msg)
        agent_users.update_one({'user_id': user_id}, {'$set': {'sign':  '0'}})
        return
    
    product_name = product.get('projectname', '未知商品')
    display_product = t(product_name, lang) if lang != 'zh' else product_name
    hq_price = float(product.get('money', 0))
    agent_price = hq_price * (1 + COMMISSION_RATE)
    
    # 验证输入是否为数字
    if not text.isdigit():
        cancel_text = "❌ Cancel" if lang != 'zh' else "❌ 取消购买"
        keyboard = [[InlineKeyboardButton(cancel_text, callback_data=f"close_{user_id}")]]
        msg = "Please enter a number, click cancel if not purchasing" if lang != 'zh' else "请输入数字，不购买请点击取消"
        update.message.reply_text(
            msg,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    quantity = int(text)
    
    # 验证数量是否有效
    if quantity <= 0:
        back_text = "🔙 Back to Products" if lang != 'zh' else "🔙 返回商品列表"
        keyboard = [[InlineKeyboardButton(back_text, callback_data="product_list")]]
        if lang == 'zh':
            msg = "❌ 购买数量必须大于0\n\n请返回商品列表重新购买"
        else: 
            msg = "❌ Quantity must be greater than 0\n\nPlease go back and try again"
        update.message.reply_text(
            msg,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        agent_users.update_one({'user_id': user_id}, {'$set': {'sign': '0'}})
        return
    
    # 检查库存
    current_stock = get_real_time_stock(nowuid)
    if current_stock < quantity: 
        cancel_text = "❌ Cancel" if lang != 'zh' else "❌ 取消购买"
        keyboard = [[InlineKeyboardButton(cancel_text, callback_data=f"close_{user_id}")]]
        msg = "Insufficient stock, please enter quantity again" if lang != 'zh' else "当前库存不足【请再次输入数量】"
        update.message.reply_text(
            msg,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # 计算总价
    total_price = standard_num(quantity * agent_price)
    total_price = float(total_price) if '.' in str(total_price) else int(total_price)
    
    # 获取余额
    balance = agent_user.get('USDT', 0)
    
    # 显示确认订单页面
    if lang == 'zh':
        text = f"""
<b>✅您正在购买：{product_name}

✅ 数量：{quantity}

💰 价格：{total_price}

💰 您的余额：{balance:.2f}</b>
        """.strip()
        
        keyboard = [
            [
                InlineKeyboardButton("❌ 取消交易", callback_data=f"close_{user_id}"),
                InlineKeyboardButton("确认购买 ✅", callback_data=f"confirm_buy_{nowuid}:{quantity}:{total_price}")
            ],
            [InlineKeyboardButton("🏠 主菜单", callback_data="back_to_main")]
        ]
    else:
        text = f"""
<b>✅ You are purchasing: {display_product}

✅ Quantity: {quantity}

💰 Price: {total_price}

💰 Your Balance: {balance:.2f}</b>
        """.strip()
        
        keyboard = [
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"close_{user_id}"),
                InlineKeyboardButton("Confirm ✅", callback_data=f"confirm_buy_{nowuid}:{quantity}:{total_price}")
            ],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="back_to_main")]
        ]
    
    # 清除状态
    agent_users.update_one({'user_id':user_id},{'$set':{'sign':'0'}})
    
    update.message.reply_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def send_account_files(context: CallbackContext, user_id: int, nowuid: str, quantity: int):
    """打包并发送账号文件"""
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 从数据库获取指定数量的账号
    query_condition = {"nowuid":  nowuid, "state": 0}
    pipeline = [
        {"$match": query_condition},
        {"$limit": quantity}
    ]
    
    cursor = hb.aggregate(pipeline)
    accounts = list(cursor)
    
    if len(accounts) < quantity:
        logging.error(f"库存不足: 需要{quantity}个，实际只有{len(accounts)}个")
        msg = "❌ Out of stock, purchase failed" if lang != 'zh' else "❌ 库存不足，购买失败"
        context.bot.send_message(
            chat_id=user_id,
            text=msg
        )
        return False
    
    # 获取账号文件名
    folder_names = [doc['projectname'] for doc in accounts]
    
    # 创建zip文件
    timestamp = int(time.time())
    zip_filename = f"./协议号发货/{user_id}_{timestamp}.zip"
    
    # 确保目录存在
    os.makedirs('./协议号发货', exist_ok=True)
    
    # 打包文件
    try:
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_name in folder_names:
                # 从总部账号目录读取
                json_file = os.path.join(BASE_PROTOCOL_PATH, nowuid, file_name + ".json")
                session_file = os.path.join(BASE_PROTOCOL_PATH, nowuid, file_name + ".session")
                
                # 如果总部路径不存在，尝试本地路径
                if not os.path.exists(json_file):
                    json_file = os.path.join(FALLBACK_PROTOCOL_PATH, nowuid, file_name + ".json")
                if not os.path.exists(session_file):
                    session_file = os.path.join(FALLBACK_PROTOCOL_PATH, nowuid, file_name + ".session")
                
                if os.path.exists(json_file):
                    zipf.write(json_file, os.path.basename(json_file))
                if os.path.exists(session_file):
                    zipf.write(session_file, os.path.basename(session_file))
        
        # 发送成功消息
        if lang == 'zh':
            success_text = """
✅ 您的账户已打包完成，请查收！

🔐二级密码:请在json文件中【two2fa】查看！

⚠️注意：请马上检查账户，1小时内出现问题，联系客服处理！

‼️ 超过售后时间，损失自付，无需多言！

♦️ 客服 {customer_service}
            """.format(customer_service=CUSTOMER_SERVICE).strip()
            
            keyboard = [[InlineKeyboardButton("✅ 已读（点击销毁此消息）", callback_data=f"close_{user_id}")]]
        else:
            success_text = """
✅ Your accounts have been packaged, please check!

🔐 2FA Password: Check【two2fa】in the json file!

⚠️ Note: Please check accounts immediately. Contact support within 1 hour if there are issues! 

‼️ After support period, losses are your responsibility! 

♦️ Support {customer_service}
            """.format(customer_service=CUSTOMER_SERVICE).strip()
            
            keyboard = [[InlineKeyboardButton("✅ Got it (click to dismiss)", callback_data=f"close_{user_id}")]]
        
        context.bot.send_message(
            chat_id=user_id,
            text=success_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # 发送文件
        with open(zip_filename, "rb") as f:
            context.bot.send_document(chat_id=user_id, document=f)
        
        # 标记账号为已售出
        timer = beijing_now_str()
        document_ids = [doc['_id'] for doc in accounts]
        update_data = {"$set":  {'state': 1, 'yssj': timer, 'gmid': user_id}}
        hb.update_many({"_id": {"$in":  document_ids}}, update_data)
        
        # 清理临时文件
        try:
            os.remove(zip_filename)
        except Exception as e:
            logging.warning(f"清理临时文件失败: {e}")
        
        return True
        
    except Exception as e: 
        logging.error(f"打包发送文件失败: {e}")
        import traceback
        traceback.print_exc()
        msg = "❌ Failed to package files, please contact support" if lang != 'zh' else "❌ 打包文件失败，请联系客服"
        context.bot.send_message(
            chat_id=user_id,
            text=msg
        )
        return False


def send_account_files_with_detection(context: CallbackContext, user_id: int, nowuid: str, quantity: int, 
                                       product_name: str, agent_price: float, order_id: str):
    """
    打包并发送账号文件（带智能检测）
    
    Returns:
        (success, refund_amount)
    """
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 检查是否启用检测
    if not ENABLE_ACCOUNT_DETECTION or not ACCOUNT_DETECTOR_AVAILABLE or not API_ID or not API_HASH:
        logging.warning("账号检测未启用或配置不完整，使用普通发货")
        return send_account_files(context, user_id, nowuid, quantity), 0.0
    
    # 从数据库获取指定数量的账号
    query_condition = {"nowuid": nowuid, "state": 0}
    pipeline = [
        {"$match": query_condition},
        {"$limit": quantity}
    ]
    
    cursor = hb.aggregate(pipeline)
    accounts = list(cursor)
    
    if len(accounts) < quantity:
        logging.error(f"库存不足: 需要{quantity}个，实际只有{len(accounts)}个")
        msg = "❌ Out of stock, purchase failed" if lang != 'zh' else "❌ 库存不足，购买失败"
        context.bot.send_message(chat_id=user_id, text=msg)
        return False, 0.0
    
    # 准备检测账号列表
    detection_accounts = []
    for account in accounts:
        file_name = account['projectname']
        
        # 查找session和json文件
        json_file = os.path.join(BASE_PROTOCOL_PATH, nowuid, file_name + ".json")
        session_file = os.path.join(BASE_PROTOCOL_PATH, nowuid, file_name + ".session")
        
        # 如果总部路径不存在，尝试本地路径
        if not os.path.exists(json_file):
            json_file = os.path.join(FALLBACK_PROTOCOL_PATH, nowuid, file_name + ".json")
        if not os.path.exists(session_file):
            session_file = os.path.join(FALLBACK_PROTOCOL_PATH, nowuid, file_name + ".session")
        
        detection_accounts.append({
            'phone': file_name,
            'session': session_file.replace('.session', ''),  # Telethon不需要.session后缀
            'json': json_file,
            'db_id': account['_id']
        })
    
    # 发送检测开始消息
    if lang == 'zh':
        progress_text = """🔍 正在检测账号质量... 

━━━━━━━━━━━━━━━━━━━━
📊 检测进度: 0/{total}

✅ 正常: 0
❌ 封禁: 0
⚠️ 冻结: 0
❓ 未知: 0

⏳ 检测中...
━━━━━━━━━━━━━━━━━━━━""".format(total=quantity)
    else:
        progress_text = """🔍 Checking account quality... 

━━━━━━━━━━━━━━━━━━━━
📊 Progress: 0/{total}

✅ Normal: 0
❌ Banned: 0
⚠️ Frozen: 0
❓ Unknown: 0

⏳ Checking...
━━━━━━━━━━━━━━━━━━━━""".format(total=quantity)
    
    progress_msg = context.bot.send_message(
        chat_id=user_id,
        text=progress_text
    )
    
    # 进度回调函数
    def update_progress(current, total, results):
        try:
            if lang == 'zh':
                updated_text = """🔍 正在检测账号质量... 

━━━━━━━━━━━━━━━━━━━━
📊 检测进度: {current}/{total}

✅ 正常: {normal}
❌ 封禁: {banned}
⚠️ 冻结: {frozen}
❓ 未知: {unknown}

⏳ 检测中...
━━━━━━━━━━━━━━━━━━━━""".format(
                    current=current,
                    total=total,
                    normal=len(results.get('normal', [])),
                    banned=len(results.get('banned', [])),
                    frozen=len(results.get('frozen', [])),
                    unknown=len(results.get('unknown', []))
                )
            else:
                updated_text = """🔍 Checking account quality... 

━━━━━━━━━━━━━━━━━━━━
📊 Progress: {current}/{total}

✅ Normal: {normal}
❌ Banned: {banned}
⚠️ Frozen: {frozen}
❓ Unknown: {unknown}

⏳ Checking...
━━━━━━━━━━━━━━━━━━━━""".format(
                    current=current,
                    total=total,
                    normal=len(results.get('normal', [])),
                    banned=len(results.get('banned', [])),
                    frozen=len(results.get('frozen', [])),
                    unknown=len(results.get('unknown', []))
                )
            
            context.bot.edit_message_text(
                chat_id=user_id,
                message_id=progress_msg.message_id,
                text=updated_text
            )
        except Exception as e:
            logging.error(f"更新进度失败: {e}")
    
    # 执行批量检测
    try:
        detector = BatchDetector(API_ID, API_HASH, max_workers=30)
        results = detector.detect_accounts(detection_accounts, progress_callback=update_progress)
    except Exception as e:
        logging.error(f"账号检测失败: {e}")
        # 检测失败，回退到普通发货
        try:
            context.bot.delete_message(chat_id=user_id, message_id=progress_msg.message_id)
        except:
            pass
        return send_account_files(context, user_id, nowuid, quantity), 0.0
    
    # 处理检测结果
    normal_count = len(results.get('normal', []))
    banned_count = len(results.get('banned', []))
    frozen_count = len(results.get('frozen', []))
    unknown_count = len(results.get('unknown', []))
    
    # 计算退款金额
    refund_count = banned_count + frozen_count
    refund_amount = refund_count * agent_price
    
    # 创建正常账号zip
    normal_zip_path = None
    if normal_count > 0:
        timestamp = int(time.time())
        normal_zip_path = f"./协议号发货/{user_id}_{timestamp}_normal.zip"
        os.makedirs('./协议号发货', exist_ok=True)
        
        with zipfile.ZipFile(normal_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for account in results['normal']:
                session_file = account['session'] + '.session'
                json_file = account['json']
                
                if os.path.exists(json_file):
                    zipf.write(json_file, os.path.basename(json_file))
                if os.path.exists(session_file):
                    zipf.write(session_file, os.path.basename(session_file))
    
    # 创建未知错误账号zip
    unknown_zip_path = None
    if unknown_count > 0:
        timestamp = int(time.time())
        unknown_zip_path = f"./协议号发货/{user_id}_{timestamp}_unknown.zip"
        os.makedirs('./协议号发货', exist_ok=True)
        
        with zipfile.ZipFile(unknown_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for account in results['unknown']:
                session_file = account['session'] + '.session'
                json_file = account['json']
                
                if os.path.exists(json_file):
                    zipf.write(json_file, os.path.basename(json_file))
                if os.path.exists(session_file):
                    zipf.write(session_file, os.path.basename(session_file))
    
    # 发送坏号到群组并删除
    if (banned_count > 0 or frozen_count > 0) and BAD_ACCOUNT_GROUP_ID:
        try:
            bad_accounts = results.get('banned', []) + results.get('frozen', [])
            for account in bad_accounts:
                session_file = account['session'] + '.session'
                json_file = account['json']
                
                # 发送文件到坏号群
                try:
                    group_id = int(BAD_ACCOUNT_GROUP_ID)
                    if os.path.exists(json_file):
                        with open(json_file, 'rb') as f:
                            context.bot.send_document(
                                chat_id=group_id,
                                document=f,
                                caption=f"❌ 坏号: {account['phone']}\n状态: {'封禁' if account in results.get('banned', []) else '冻结'}\n订单: {order_id}"
                            )
                    if os.path.exists(session_file):
                        with open(session_file, 'rb') as f:
                            context.bot.send_document(
                                chat_id=group_id,
                                document=f
                            )
                except Exception as e:
                    logging.error(f"发送坏号到群组失败: {e}")
                
                # 删除坏号文件
                try:
                    if os.path.exists(json_file):
                        os.remove(json_file)
                    if os.path.exists(session_file):
                        os.remove(session_file)
                except Exception as e:
                    logging.error(f"删除坏号文件失败: {e}")
        except Exception as e:
            logging.error(f"处理坏号失败: {e}")
    
    # 删除进度消息
    try:
        context.bot.delete_message(chat_id=user_id, message_id=progress_msg.message_id)
    except:
        pass
    
    # 发送检测结果消息
    if lang == 'zh':
        result_text = f"""🛒 购买成功！

━━━━━━━━━━━━━━━━━━━━
📦 商品: {product_name}
💰 单价: {agent_price:.2f} USDT
📊 购买数量: {quantity} 个
━━━━━━━━━━━━━━━━━━━━

🔍 检测结果: 
✅ 正常: {normal_count} 个
❌ 封禁: {banned_count} 个
⚠️ 冻结: {frozen_count} 个

💰 实付: {normal_count * agent_price:.2f} USDT
{'💵 退回: ' + f'{refund_amount:.2f} USDT ✅' if refund_amount > 0 else ''}

{'📁 正常账号已发送 ↓' if normal_count > 0 else ''}"""
        
        if unknown_count > 0:
            result_text += f"""

━━━━━━━━━━━━━━━━━━━━
⚠️ 以下账号检测异常，请联系客服处理: 

❓ 未知错误: {unknown_count} 个"""
        
        result_text += "\n━━━━━━━━━━━━━━━━━━━━"
    else:
        result_text = f"""🛒 Purchase Successful！

━━━━━━━━━━━━━━━━━━━━
📦 Product: {product_name}
💰 Price: {agent_price:.2f} USDT
📊 Quantity: {quantity} pcs
━━━━━━━━━━━━━━━━━━━━

🔍 Detection Result: 
✅ Normal: {normal_count} pcs
❌ Banned: {banned_count} pcs
⚠️ Frozen: {frozen_count} pcs

💰 Paid: {normal_count * agent_price:.2f} USDT
{'💵 Refund: ' + f'{refund_amount:.2f} USDT ✅' if refund_amount > 0 else ''}

{'📁 Normal accounts sent ↓' if normal_count > 0 else ''}"""
        
        if unknown_count > 0:
            result_text += f"""

━━━━━━━━━━━━━━━━━━━━
⚠️ Following accounts have detection errors, please contact support: 

❓ Unknown Error: {unknown_count} pcs"""
        
        result_text += "\n━━━━━━━━━━━━━━━━━━━━"
    
    context.bot.send_message(
        chat_id=user_id,
        text=result_text
    )
    
    # 发送正常账号zip
    if normal_zip_path and os.path.exists(normal_zip_path):
        with open(normal_zip_path, 'rb') as f:
            context.bot.send_document(
                chat_id=user_id,
                document=f,
                filename="正常账号.zip" if lang == 'zh' else "normal_accounts.zip"
            )
        try:
            os.remove(normal_zip_path)
        except:
            pass
    
    # 发送未知错误账号zip
    if unknown_zip_path and os.path.exists(unknown_zip_path):
        with open(unknown_zip_path, 'rb') as f:
            context.bot.send_document(
                chat_id=user_id,
                document=f,
                filename="未知错误账号.zip" if lang == 'zh' else "unknown_error_accounts.zip"
            )
        try:
            os.remove(unknown_zip_path)
        except:
            pass
    
    # 标记正常和未知错误账号为已售出
    timer = beijing_now_str()
    sold_account_ids = []
    
    for account in results.get('normal', []) + results.get('unknown', []):
        sold_account_ids.append(account['db_id'])
    
    if sold_account_ids:
        hb.update_many(
            {"_id": {"$in": sold_account_ids}},
            {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}}
        )
    
    # 删除坏号数据库记录
    bad_account_ids = []
    for account in results.get('banned', []) + results.get('frozen', []):
        bad_account_ids.append(account['db_id'])
    
    if bad_account_ids:
        hb.delete_many({"_id": {"$in": bad_account_ids}})
    
    return True, refund_amount


def confirm_buy_product(update: Update, context:  CallbackContext):
    """确认购买商品（执行购买）"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    username = query.from_user.username or 'unknown'
    fullname = query.from_user.full_name.replace('<', '').replace('>', '')
    
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 从callback_data中提取信息:  confirm_buy_{nowuid}:{quantity}:{total_price}
    data = query.data.replace("confirm_buy_", "")
    parts = data.split(':')
    
    if len(parts) != 3:
        msg = "❌ Data format error" if lang != 'zh' else "❌ 数据格式错误"
        query.answer(msg,show_alert=True)
        return
    
    nowuid = parts[0]
    quantity = int(parts[1])
    total_price = float(parts[2])
    
    try:
        # 获取商品信息
        product = ejfl.find_one({'nowuid': nowuid})
        if not product:
            msg = "Product not found" if lang != 'zh' else "商品不存在"
            query.answer(msg,show_alert=True)
            return
        
        product_name = product.get('projectname', '未知商品')
        display_product = t(product_name, lang) if lang != 'zh' else product_name
        hq_price = float(product.get('money', 0))
        agent_price = hq_price * (1 + COMMISSION_RATE)
        hq_total_price = hq_price * quantity
        profit = total_price - hq_total_price
        
        # 获取商品类型
        fhtype = product.get('leixing', '协议号')
        if not fhtype: 
            stock_item = hb.find_one({'nowuid': nowuid, 'state': 0})
            if stock_item:
                fhtype = stock_item.get('leixing', '协议号')
            else:
                fhtype = '协议号'
        
        # 检查库存
        current_stock = get_real_time_stock(nowuid)
        if current_stock < quantity: 
            msg = "❌ Out of stock" if lang != 'zh' else "❌ 库存不足"
            query.answer(msg,show_alert=True)
            return
        
        # 获取用户余额
        agent_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
        if not agent_user:
            msg = "User not found" if lang != 'zh' else "用户不存在"
            query.answer(msg,show_alert=True)
            return
        
        balance = agent_user.get('USDT', 0)
        
        # 再次检查余额
        if balance < total_price:
            msg = "❌ Insufficient balance" if lang != 'zh' else "❌ 余额不足"
            query.answer(msg,show_alert=True)
            return
        
        # 扣减余额
        agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
        agent_users.update_one(
            {'user_id': user_id},
            {
                '$inc':  {
                    'USDT': -total_price,
                    'zgje': total_price,
                    'zgsl': quantity
                }
            }
        )
        
        # 记录订单
        order_time = beijing_now_str()
        order_id = f"{AGENT_BOT_ID}_{user_id}_{int(datetime.now().timestamp())}"
        
        agent_orders.insert_one({
            'order_id':  order_id,
            'agent_bot_id': AGENT_BOT_ID,
            'customer_id': user_id,
            'original_nowuid': nowuid,
            'product_name': product_name,
            'quantity': quantity,
            'headquarters_price': hq_price,
            'agent_price': agent_price,
            'total_price': total_price,
            'profit': profit,
            'commission':  profit,
            'status':  'completed',
            'order_time': order_time,
            'delivery_type': fhtype
        })
        
        # 发送订单通知到群组
        try:
            updated_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
            total_spent = updated_user.get('zgje', 0) if updated_user else 0
            new_balance = updated_user.get('USDT', 0) if updated_user else 0
            
            total_orders_count = agent_orders.count_documents({
                'agent_bot_id':  AGENT_BOT_ID,
                'customer_id': user_id,
                'status':  'completed'
            })
            
            profit_per_unit = profit / quantity if quantity > 0 else 0
            
            order_notify_data = {
                'username': username,
                'user_id': user_id,
                'order_id': order_id,
                'order_time': order_time,
                'category': fhtype,
                'product_name': product_name,
                'quantity': quantity,
                'total_price': total_price,
                'hq_total_price': hq_total_price,
                'agent_price': agent_price,
                'profit': profit,
                'profit_per_unit':  profit_per_unit,
                'old_balance': balance,
                'new_balance': new_balance,
                'total_spent': total_spent,
                'total_orders':  total_orders_count
            }
            
            send_order_notify_to_group('purchase', order_notify_data, bot=context.bot)
        except Exception as notify_error:
            logging.error(f"❌ 发送购买订单通知失败:  {notify_error}")
        
        # 记录购买记录到代理gmjlu
        agent_gmjlu = get_agent_bot_gmjlu_collection(AGENT_BOT_ID)
        agent_gmjlu.insert_one({
            'leixing': 'purchase',
            'bianhao': order_id,
            'user_id': user_id,
            'projectname': product_name,
            'text': f'购买数量: {quantity}',
            'ts': total_price,
            'timer': order_time,
            'count': quantity,
            'price': agent_price,
            'total_price': total_price
        })
        
        # 更新代理总销售额和佣金
        agent_bots.update_one(
            {'agent_bot_id': AGENT_BOT_ID},
            {
                '$inc': {
                    'total_sales': total_price,
                    'total_commission': profit,
                    'available_balance': profit,
                    'total_orders': 1
                }
            }
        )
        
        # 删除确认消息
        try:
            query.delete_message()
        except Exception as e:
            logging.warning(f"删除确认消息失败: {e}")
        
        # 根据商品类型发送账号
        if fhtype == '协议号':
            # 使用带检测的发货功能
            success, refund_amount = send_account_files_with_detection(
                context, user_id, nowuid, quantity, product_name, agent_price, order_id
            )
            
            if not success:
                # 发货失败，全额退款
                agent_users.update_one(
                    {'user_id': user_id},
                    {
                        '$inc': {
                            'USDT': total_price,
                            'zgje':  -total_price,
                            'zgsl': -quantity
                        }
                    }
                )
                agent_orders.update_one(
                    {'order_id': order_id},
                    {'$set': {'status': 'failed', 'error': '发货失败，已退款'}}
                )
                # 回退代理统计
                agent_bots.update_one(
                    {'agent_bot_id': AGENT_BOT_ID},
                    {
                        '$inc': {
                            'total_sales': -total_price,
                            'total_commission': -profit,
                            'available_balance': -profit,
                            'total_orders': -1
                        }
                    }
                )
                return
            
            # 处理退款（如果有坏号）
            if refund_amount > 0:
                # 退款给用户
                agent_users.update_one(
                    {'user_id': user_id},
                    {'$inc': {'USDT': refund_amount, 'zgje': -refund_amount}}
                )
                
                # 更新订单记录
                agent_orders.update_one(
                    {'order_id': order_id},
                    {
                        '$set': {
                            'refund_amount': refund_amount,
                            'final_price': total_price - refund_amount
                        }
                    }
                )
                
                # 调整代理统计
                refund_profit = refund_amount - (refund_amount / (1 + COMMISSION_RATE) * COMMISSION_RATE)
                agent_bots.update_one(
                    {'agent_bot_id': AGENT_BOT_ID},
                    {
                        '$inc': {
                            'total_sales': -refund_amount,
                            'total_commission': -refund_profit,
                            'available_balance': -refund_profit
                        }
                    }
                )
                
                logging.info(f"✅ 退款处理完成: user={user_id}, refund={refund_amount:.2f}")
        else:
            accounts = list(hb.find({"nowuid": nowuid, 'state': 0}).limit(quantity))
            
            if len(accounts) < quantity:
                if lang == 'zh': 
                    context.bot.send_message(chat_id=user_id, text="❌ 库存不足，购买失败")
                else:
                    context.bot.send_message(chat_id=user_id, text="❌ Out of stock, purchase failed")
                agent_users.update_one(
                    {'user_id':  user_id},
                    {
                        '$inc': {
                            'USDT': total_price,
                            'zgje': -total_price,
                            'zgsl': -quantity
                        }
                    }
                )
                return
            
            timer = beijing_now_str()
            for account in accounts: 
                hb.update_one(
                    {'_id': account['_id']},
                    {'$set': {'state': 1, 'yssj': timer, 'gmid': user_id}}
                )
            
            content_list = []
            for account in accounts:
                content_list.append(account.get('hbid', ''))
            
            content = '\n'.join(content_list)
            
            if lang == 'zh': 
                success_text = f"""
✅ <b>购买成功</b>

📦 商品: {product_name}
📊 数量: {quantity}
💰 支付: <code>{total_price:.2f}</code> USDT
💵 剩余余额: <code>{balance - total_price:.2f}</code> USDT

📝 <b>商品内容:</b>
<code>{content}</code>

⏰ 购买时间: {order_time}
📋 订单号: <code>{order_id}</code>

💡 如有问题请联系客服
                """.strip()
                
                keyboard = [
                    [InlineKeyboardButton("🛒 继续购买", callback_data="product_list")],
                    [InlineKeyboardButton("📋 我的订单", callback_data="my_orders")]
                ]
            else:
                success_text = f"""
✅ <b>Purchase Successful</b>

📦 Product: {display_product}
📊 Quantity:  {quantity}
💰 Paid:  <code>{total_price:.2f}</code> USDT
💵 Remaining: <code>{balance - total_price:.2f}</code> USDT

📝 <b>Account Details:</b>
<code>{content}</code>

⏰ Time: {order_time}
📋 Order ID: <code>{order_id}</code>

💡 Contact support if you have any issues
                """.strip()
                
                keyboard = [
                    [InlineKeyboardButton("🛒 Continue Shopping", callback_data="product_list")],
                    [InlineKeyboardButton("📋 My Orders", callback_data="my_orders")]
                ]
            
            context.bot.send_message(
                chat_id=user_id,
                text=success_text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        logging.info(f"✅ 代理订单完成:  user={user_id}, product={product_name}, quantity={quantity}, amount={total_price:.2f}")
        
    except Exception as e: 
        logging.error(f"❌ 购买失败: {e}")
        import traceback
        traceback.print_exc()
        try:
            msg = "❌ Purchase failed, please contact support" if lang != 'zh' else "❌ 购买失败，请联系客服"
            context.bot.send_message(chat_id=user_id, text=msg)
        except Exception as e:
            logging.error(f"发送错误消息失败:  {e}")

def show_recharge(update: Update, context: CallbackContext):
    """显示充值金额选择"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 检查支付系统是否可用
    if not PAYMENT_SYSTEM_AVAILABLE: 
        if lang == 'zh': 
            text = """
💳 <b>余额充值</b>

请联系客服进行充值

📞 客服联系方式: 
（管理员配置）

💡 充值后请告知客服您的用户ID，
   客服将为您手动充值。
            """.strip()
            
            keyboard = [
                [InlineKeyboardButton("📞 联系客服", callback_data="contact_support")],
                [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]
            ]
        else:
            text = """
💳 <b>Recharge Balance</b>

Please contact support to recharge

📞 Contact Support:
(Admin configured)

💡 After recharge, please provide your User ID,
   support will manually add balance for you.
            """.strip()
            
            keyboard = [
                [InlineKeyboardButton("📞 Contact Support", callback_data="contact_support")],
                [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")]
            ]
        
        # 删除原消息并发送新消息（兼容图片消息）
        try:
            query.message.delete()
        except Exception as e:
            logging.debug(f"删除消息失败（预期行为）: {e}")
        context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # 显示充值金额选择
    if lang == 'zh':
        text = """💳 <b>充值余额</b>

请选择充值金额："""
        
        keyboard = [
            [
                InlineKeyboardButton("10 USDT", callback_data="recharge_amount_10"),
                InlineKeyboardButton("20 USDT", callback_data="recharge_amount_20"),
                InlineKeyboardButton("50 USDT", callback_data="recharge_amount_50")
            ],
            [
                InlineKeyboardButton("100 USDT", callback_data="recharge_amount_100"),
                InlineKeyboardButton("200 USDT", callback_data="recharge_amount_200"),
                InlineKeyboardButton("500 USDT", callback_data="recharge_amount_500")
            ],
            [InlineKeyboardButton("📝 自定义金额", callback_data="recharge_custom")],
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]
        ]
    else:
        text = """💳 <b>Recharge Balance</b>

Please select recharge amount:"""
        
        keyboard = [
            [
                InlineKeyboardButton("10 USDT", callback_data="recharge_amount_10"),
                InlineKeyboardButton("20 USDT", callback_data="recharge_amount_20"),
                InlineKeyboardButton("50 USDT", callback_data="recharge_amount_50")
            ],
            [
                InlineKeyboardButton("100 USDT", callback_data="recharge_amount_100"),
                InlineKeyboardButton("200 USDT", callback_data="recharge_amount_200"),
                InlineKeyboardButton("500 USDT", callback_data="recharge_amount_500")
            ],
            [InlineKeyboardButton("📝 Custom Amount", callback_data="recharge_custom")],
            [InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main")]
        ]
    
    # 删除原消息并发送新消息（兼容图片消息）
    try: 
        query.message.delete()
    except Exception as e:
        logging.debug(f"删除消息失败（预期行为）: {e}")
    context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def validate_recharge_amount(amount: float, lang='zh') -> tuple:
    """验证充值金额
    
    Returns:
        (is_valid:  bool, error_message: str)
    """
    try: 
        # 从支付系统配置获取限制（如果可用）
        if PAYMENT_SYSTEM_AVAILABLE:
            from agentzfxt import Config
            min_amount = Config.MIN_RECHARGE_AMOUNT
            max_amount = Config.MAX_RECHARGE_AMOUNT
        else: 
            # 默认限制
            min_amount = 1
            max_amount = 10000
        
        if amount < min_amount: 
            if lang == 'zh':
                return False, f"❌ 充值金额不能小于 {min_amount} USDT"
            else: 
                return False, f"❌ Minimum amount is {min_amount} USDT"
        if amount > max_amount: 
            if lang == 'zh': 
                return False, f"❌ 充值金额不能大于 {max_amount} USDT"
            else:
                return False, f"❌ Maximum amount is {max_amount} USDT"
        
        return True, ""
    except Exception as e: 
        logging.error(f"验证充值金额失败: {e}")
        if lang == 'zh':
            return False, "❌ 金额验证失败"
        else:
            return False, "❌ Amount validation failed"


def handle_recharge_amount(update: Update, context: CallbackContext):
    """处理充值金额选择"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 从callback_data提取金额
    amount_str = query.data.replace("recharge_amount_", "")
    
    try: 
        amount = float(amount_str)
        
        # 验证金额范围
        is_valid, error_msg = validate_recharge_amount(amount, lang)
        if not is_valid:
            query.answer(error_msg, show_alert=True)
            return
        
        # 创建充值订��
        create_recharge_order(update, context, amount)
        
    except ValueError:
        msg = "❌ Invalid amount format" if lang != 'zh' else "❌ 金额格式错误"
        query.answer(msg, show_alert=True)


def handle_recharge_custom(update: Update, context: CallbackContext):
    """处理自定义金额按钮"""
    query = update.callback_query
    query.answer()
    
    user_id = update.effective_user.id
    
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    # 设置状态，等待用户输入金额
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    agent_users.update_one(
        {'user_id': user_id},
        {'$set': {'sign': 'recharge_custom_amount'}}
    )
    
    if lang == 'zh':
        text = """💳 <b>自定义充值金额</b>

请输入充值金额（USDT）：

📌 最小金额：1 USDT
📌 最大金额：10000 USDT

💡 输入数字后发送即可"""
        
        keyboard = [[InlineKeyboardButton("❌ 取消", callback_data="recharge")]]
    else:
        text = """💳 <b>Custom Recharge Amount</b>

Please enter the recharge amount (USDT):

📌 Minimum: 1 USDT
📌 Maximum: 10000 USDT

💡 Enter the amount and send"""
        
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="recharge")]]
    
    try:
        query.message.delete()
    except Exception: 
        pass
    context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def handle_custom_amount_input(update: Update, context: CallbackContext, user_id: int, text:  str):
    """处理自定义金额输入"""
    # 获取用户语言
    lang = get_user_lang(user_id)
    
    try:
        amount = float(text)
        
        # 使用统一的验证函数
        is_valid, error_msg = validate_recharge_amount(amount, lang)
        if not is_valid:
            update.message.reply_text(error_msg)
            return
        
        # 重置状态
        agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
        agent_users.update_one(
            {'user_id': user_id},
            {'$set': {'sign':  '0'}}
        )

    
        # 创建充值订单
        create_recharge_order(update, context, amount)
        
    except ValueError: 
        msg = "❌ Please enter a valid number" if lang != 'zh' else "❌ 请输入有效的数字金额"
        update.message.reply_text(msg)
        
def generate_qrcode(address):
    """生成钱包地址二维码"""
    qr = qrcode.make(address)
    buffer = BytesIO()
    qr.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer
    

def create_recharge_order(update: Update, context: CallbackContext, amount: float):
    """创建充值订单并显示支付页面"""
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    
    if not PAYMENT_SYSTEM_AVAILABLE: 
        msg = "❌ Payment system unavailable" if lang != 'zh' else "❌ 支付系统不可用"
        if update.callback_query:
            update.callback_query.answer(msg, show_alert=True)
        else:
            update.message.reply_text(msg)
        return
    
    try:
        # 获取支付系统
        payment_system = get_payment_system()
        
        # 先发送一个占位消息，获取message_id
        if update.callback_query:
            chat_id = update.callback_query.message.chat_id
            # 删除原消息
            try:
                update.callback_query.message.delete()
            except Exception:
                pass
        else:
            chat_id = update.message.chat_id
        
        loading_msg = "⏳ Creating order..." if lang != 'zh' else "⏳ 正在创建充值订单..."
        placeholder_msg = context.bot.send_message(
            chat_id=chat_id,
            text=loading_msg
        )
        
        # 创建订单
        order_info = payment_system.create_order(user_id, amount, placeholder_msg.message_id)
        
        if not order_info: 
            fail_msg = "❌ Failed to create order, please try again" if lang != 'zh' else "❌ 创建订单失败，请稍后重试"
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=placeholder_msg.message_id,
                text=fail_msg
            )
            return
        
        order_id = order_info['order_id']
        exact_amount = order_info['exact_amount']
        
        # 获取充值地址
        deposit_address = os.getenv('AGENT_DEPOSIT_ADDRESS', '')
        
        # 删除占位消息
        try: 
            context.bot.delete_message(chat_id=chat_id, message_id=placeholder_msg.message_id)
        except: 
            pass
        
        # 生成二维码
        qr_image = generate_qrcode(deposit_address)
        
        # 消息文字
        if lang == 'zh': 
            caption = f"""🏷 充值详情

💰 付款金额: <code>{exact_amount:.4f}</code> USDT

📍 唯一收款地址(TRC20)
<code>{deposit_address}</code>

⚠️ 重要提示
🔸请按照金额后小数点转账
🔸充值后, 经过3次网络确认, 充值成功!  
🔸请耐心等待, 充值成功后 Bot 会通知您!  

📋 订单号: <code>{order_id}</code>
⏰ 有效期: 10 分钟"""

            keyboard = [
                [InlineKeyboardButton("❌ 取消订单", callback_data=f"cancel_order_{order_id}")],
                [InlineKeyboardButton("🔙 返回", callback_data="back_to_main")]
            ]
        else:
            caption = f"""🏷 Recharge Details

💰 Amount: <code>{exact_amount:.4f}</code> USDT

📍 Deposit Address (TRC20)
<code>{deposit_address}</code>

⚠️ Important
🔸Please transfer the exact amount including decimals
🔸After 3 network confirmations, recharge will be completed
🔸Please wait patiently, Bot will notify you when done

📋 Order ID: <code>{order_id}</code>
⏰ Valid for: 10 minutes"""

            keyboard = [
                [InlineKeyboardButton("❌ Cancel Order", callback_data=f"cancel_order_{order_id}")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
            ]
        
        # 发送带二维码的图片
        qr_msg = context.bot.send_photo(
            chat_id=chat_id,
            photo=qr_image,
            caption=caption,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # 更新订单的 message_id 为二维码消息的 ID
        payment_system.db_manager.topup.update_one(
            {'order_id': order_id},
            {'$set': {'message_id': qr_msg.message_id}}
        )
        
        logging.info(f"✅ 创建充值订单成功: user_id={user_id}, order_id={order_id}, amount={amount}")
        
    except Exception as e: 
        logging.error(f"❌ 创建充值订单失败: {e}")
        error_text = "❌ Failed to create order, please try again" if lang != 'zh' else "❌ 创建订单失败，请稍后重试"
        if update.callback_query:
            update.callback_query.answer(error_text, show_alert=True)
        else:
            update.message.reply_text(error_text)
            
            
            
def cancel_recharge_order(update:  Update, context: CallbackContext):
    """取消充值订单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    
    if not PAYMENT_SYSTEM_AVAILABLE:
        msg = "❌ Payment system unavailable" if lang != 'zh' else "❌ 支付系统不可用"
        query.answer(msg, show_alert=True)
        return
    
    # 从callback_data提取订单ID
    order_id = query.data.replace("cancel_order_", "")
    
    try: 
        # 获取支付系统
        payment_system = get_payment_system()
        
        # 取消订单
        success = payment_system.cancel_order(order_id)
        
        if success: 
            # 删除二维码消息
            try: 
                query.message.delete()
            except:
                pass
            msg = "✅ Order cancelled" if lang != 'zh' else "✅ 订单已取消"
            query.answer(msg, show_alert=True)
            logging.info(f"✅ 用户取消充值订单:  order_id={order_id}")
        else:
            msg = "❌ Failed to cancel order" if lang != 'zh' else "❌ 订单取消失败"
            query.answer(msg, show_alert=True)
            
    except Exception as e:
        logging.error(f"❌ 取消充值订单失败: {e}")
        msg = "❌ Failed to cancel order" if lang != 'zh' else "❌ 取消订单失败"
        query.answer(msg, show_alert=True)

def show_contact_support(update: Update, context: CallbackContext):
    """显示客服联系方式"""
    query = update.callback_query
    query.answer()
    
    text = f"""
📞 <b>联系客服</b>

客服联系方式:
{CUSTOMER_SERVICE}

💡 如有问题请直接联系客服
    """.strip()
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]
    ]
    
    # 删除原消息并发送新消息（兼容图片消息）
    try:
        query.message.delete()
    except Exception:
        pass
    context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_purchase_notice(update:  Update, context: CallbackContext):
    """显示购买须知"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    
    # 根据语言选择配置
    if lang == 'en':
        if PURCHASE_NOTICE_EN:
            notice_text = PURCHASE_NOTICE_EN.replace('\\n', '\n')
        else: 
            notice_text = """⚠️ Purchase Notice: 

1.First-time buyers are advised to test with a small purchase
2.Account prices may fluctuate based on market conditions
3.Please check the account status promptly after purchase
4.Contact customer service within 1 hour if there are any issues
5.After the warranty period, losses are borne by the buyer"""
        
        text = f"""
📖 <b>Purchase Notice</b>

{notice_text}

💡 If you have any questions, please contact customer service
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")]
        ]
    else:
        if PURCHASE_NOTICE:
            notice_text = PURCHASE_NOTICE.replace('\\n', '\n')
        else:
            notice_text = """⚠️ 购买须知：

1.首次购买建议先少量测试
2.账号价格会根据市场有所浮动
3.购买后请及时检查账号状态
4.如有问题请在1小时内联系客服
5.超过售后时间，损失自付"""
        
        text = f"""
📖 <b>购买须知</b>

{notice_text}

💡 如有疑问请联系客服
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]
        ]
    
    # 删除原消息并发送新消息（兼容图片消息）
    try:
        query.message.delete()
    except Exception as e:
        logging.debug(f"删除消息失败（预期行为）: {e}")
    context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_purchase_history(update:  Update, context: CallbackContext):
    """显示购买记录"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    
    # 从agent_orders集合获取用户订单
    orders = list(
        agent_orders.find({
            'agent_bot_id': AGENT_BOT_ID,
            'customer_id': user_id
        }).sort('order_time', -1).limit(20)
    )
    
    if not orders:
        if lang == 'en':
            text = "📋 <b>Purchase History</b>\n\nNo purchase records"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")]]
        else:
            text = "📋 <b>购买记录</b>\n\n暂无购买记录"
            keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]]
    else:
        if lang == 'en':
            text = f"📋 <b>Purchase History</b>\n\nRecent {len(orders)} orders:"
        else:
            text = f"📋 <b>购买记录</b>\n\n最近 {len(orders)} 笔订单："
        
        # 清空并重新创建订单ID映射
        context.user_data['order_id_map'] = {}
        
        keyboard = []
        for i,order in enumerate(orders, 1):
            order_id = order.get('order_id', '')
            product_name = order.get('product_name', '未知商品')
            # 翻译商品名
            display_product = t(product_name, lang) if lang == 'en' else product_name
            quantity = order.get('quantity', 0)
            order_time = order.get('order_time', '')
            
            # 截取时间显示 (月-日 时: 分)
            order_time_short = order_time[5:16] if len(order_time) > 16 else order_time
            
            # 存储订单ID映射
            context.user_data['order_id_map'][str(i)] = order_id
            
            # 每个订单一个按钮
            keyboard.append([
                InlineKeyboardButton(
                    f"{display_product} | {quantity}{'pcs' if lang == 'en' else '个'} | {order_time_short}",
                    callback_data=f"order_detail_{i}"
                )
            ])
        
        if lang == 'en':
            keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_main")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")])
    
    # 删除原消息并发送新消息
    try:
        query.message.delete()
    except Exception as e:
        logging.debug(f"删除消息失败:  {e}")
    context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_order_detail(update: Update, context:   CallbackContext):
    """显示订单详情"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    
    # 从callback_data提取订单索引
    order_index = query.data.replace("order_detail_", "")
    
    # 从context.user_data获取真实的order_id
    order_id_map = context.user_data.get('order_id_map', {})
    order_id = order_id_map.get(order_index)
    
    if not order_id: 
        if lang == 'en':
            query.answer("❌ Order info expired, please check purchase history again", show_alert=True)
        else:
            query.answer("❌ 订单信息已过期，请重新查看购买记录", show_alert=True)
        return
    
    # 获取订单信息
    order = agent_orders.find_one({
        'order_id': order_id,
        'customer_id': user_id,
        'agent_bot_id': AGENT_BOT_ID
    })
    
    if not order:
        if lang == 'en': 
            query.answer("❌ Order not found", show_alert=True)
        else:
            query.answer("❌ 订单不存在", show_alert=True)
        return
    
    product_name = order.get('product_name', '未知商品')
    # 翻译商品名
    display_product = t(product_name, lang) if lang == 'en' else product_name
    quantity = order.get('quantity', 0)
    agent_price = order.get('agent_price', 0)
    total_price = order.get('total_price', agent_price * quantity)
    order_time = order.get('order_time', '')
    status = order.get('status', 'completed')
    
    # 状态显示
    if lang == 'en':  
        status_text = "✅ Completed" if status == 'completed' else "⏳ Processing"
        text = f"""📦 <b>Order Details</b>

📋 Order ID:  <code>{order_id}</code>
📅 Time:  {order_time[: 16] if len(order_time) > 16 else order_time}
━━━━━━━━━━━━━━━━━━
🏷 {display_product}
💰 Unit Price: {agent_price:.2f} USDT
📊 Quantity: {quantity} pcs
💵 Total: {total_price:.2f} USDT
━━━━━━━━━━━━━━━━━━
{status_text}"""
        
        keyboard = [
            [InlineKeyboardButton("📥 Download File", callback_data=f"download_order_{order_index}")],
            [InlineKeyboardButton("🔙 Back to History", callback_data="purchase_history")]
        ]
    else:
        status_text = "✅ 已完成" if status == 'completed' else "⏳ 处理中"
        text = f"""📦 <b>订单详情</b>

📋 订单号:  <code>{order_id}</code>
📅 时间: {order_time[:16] if len(order_time) > 16 else order_time}
━━━━━━━━━━━━━━━━━━
🏷 {display_product}
💰 单价: {agent_price:.2f} USDT
📊 数量: {quantity} 个
💵 总价: {total_price:.2f} USDT
━━━━━━━━━━━━━━━━━━
{status_text}"""
        
        keyboard = [
            [InlineKeyboardButton("📥 下载文件", callback_data=f"download_order_{order_index}")],
            [InlineKeyboardButton("🔙 返回购买记录", callback_data="purchase_history")]
        ]
    
    try:
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logging.debug(f"编辑消息失败: {e}")
        query.message.delete()
        context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
def show_switch_lang(update: Update, context: CallbackContext):
    """显示语言切换菜单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取当前语言
    user_data = get_agent_bot_user(AGENT_BOT_ID, user_id)
    current_lang = user_data.get('lang', 'zh') if user_data else 'zh'
    
    if current_lang == 'zh': 
        text = "🌐 请选择语言 / Please select language"
    else: 
        text = "🌐 Please select language / 请选择语言"
    
    keyboard = [
        [
            InlineKeyboardButton("🇨🇳 中文" + (" ✅" if current_lang == 'zh' else ""), callback_data="set_lang_zh"),
            InlineKeyboardButton("🇺🇸 English" + (" ✅" if current_lang == 'en' else ""), callback_data="set_lang_en")
        ],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]
    ]
    
    query.edit_message_caption(
        caption=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


def set_user_lang(update: Update, context: CallbackContext):
    """设置用户语言"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取目标语言
    lang = query.data.replace("set_lang_", "")  # zh 或 en
    
    # 更新数据库
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    agent_users.update_one(
        {'user_id': user_id},
        {'$set': {'lang': lang}}
    )
    
    if lang == 'zh':
        text = "✅ 语言已切换为中文"
    else:
        text = "✅ Language changed to English"
    
    keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]]
    
    query.edit_message_caption(
        caption=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

def show_country_search(update: Update, context: CallbackContext):
    """显示国家/区号搜索提示"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    
    # 设置用户状态为等待搜索输入
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    agent_users.update_one(
        {'user_id': user_id},
        {'$set':  {'sign': 'country_search'}}
    )
    
    if lang == 'en':
        text = """
🌍 <b>Country/Code Search</b>

Please send a country name or area code
Example: UK
Example: +44

🤖 The bot will automatically find products matching your keyword
        """.strip()
        keyboard = [
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
    else:
        text = """
🌍 <b>国家/区号搜索</b>

请发送国家名称/区号
例如：英国
例如：+44

🤖 机器人将自动识别您发送的消息并向您发送包含关键词的产品
        """.strip()
        keyboard = [
            [InlineKeyboardButton("🔙 返回", callback_data="back_to_main")]
        ]
    
    # 删除原消息并发送新消息（兼容图片消息）
    try:
        query.message.delete()
    except Exception as e:
        logging.debug(f"删除消息失败（预期行为）: {e}")
    
    context.bot.send_message(
        chat_id=user_id,
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def handle_country_search_input(update: Update, context: CallbackContext, user_id: int, search_text: str):
    """处理国家/区号搜索输入"""
    lang = get_user_lang(user_id)
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    
    # 清除搜索状态
    agent_users.update_one(
        {'user_id': user_id},
        {'$set': {'sign':  '0'}}
    )
    
    # 判断输入是区号还是国家名称
    search_keyword = search_text.strip()
    
    # 如果是国家名称，转换为区号
    if search_keyword in COUNTRY_MAP:
        search_keyword = COUNTRY_MAP[search_keyword]
    
    # 从数据库搜索商品名称包含关键词的商品
    pattern = re.compile(re.escape(search_keyword), re.IGNORECASE)
    
    products = list(ejfl.find({
        'projectname': {'$regex': pattern}
    }).sort('row', 1))
    
    if not products: 
        if lang == 'en':
            text = f"""
🌍 <b>Country/Code Search</b>
🔍 <code>{search_keyword}</code> Search Results

No matching products found
            """.strip()
            keyboard = [
                [InlineKeyboardButton("🔍 Search Again", callback_data="country_search")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
            ]
        else:
            text = f"""
🌍 <b>国家/区号搜索</b>
🔍 <code>{search_keyword}</code> 搜索结果

暂无相关商品
            """.strip()
            keyboard = [
                [InlineKeyboardButton("🔍 再次搜索", callback_data="country_search")],
                [InlineKeyboardButton("🔙 返回", callback_data="back_to_main")]
            ]
        
        update.message.reply_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # 构建搜索结果消息
    if lang == 'en':
        text = f"🌍 <b>Country/Code Search</b>\n🔍 <code>{search_keyword}</code> Search Results\n\n"
    else: 
        text = f"🌍 <b>国家/区号搜索</b>\n🔍 <code>{search_keyword}</code> 搜索结果\n\n"
    
    keyboard = []
    for product in products:
        nowuid = product.get('nowuid')
        product_name = product.get('projectname', '')
        display_product = t(product_name, lang) if lang == 'en' else product_name
        hq_price = float(product.get('money', 0))
        
        # 计算代理价格
        agent_price = hq_price * (1 + COMMISSION_RATE)
        
        # 获取库存
        stock = get_real_time_stock(nowuid)
        
        # 只显示有库存的商品
        if stock > 0:
            keyboard.append([
                InlineKeyboardButton(
                    f"{display_product} - ${agent_price:.2f}",
                    callback_data=f"product_{nowuid}"
                )
            ])
    
    if not keyboard: 
        text += "No products in stock\n" if lang == 'en' else "暂无库存商品\n"
    
    keyboard.append([InlineKeyboardButton("🔍 Search Again" if lang == 'en' else "🔍 再次搜索", callback_data="country_search")])
    keyboard.append([InlineKeyboardButton("🔙 Back" if lang == 'en' else "🔙 返回", callback_data="back_to_main")])
    

    
    update.message.reply_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
def download_order(update: Update, context: CallbackContext):
    """下载订单文件"""
    query = update.callback_query
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    
    query.answer("Preparing download..." if lang == 'en' else "正在准备下载...", show_alert=False)
    
    # 从callback_data提取订单索引
    order_index = query.data.replace("download_order_", "")
    
    # 从context.user_data获取真实的order_id
    order_id_map = context.user_data.get('order_id_map', {})
    order_id = order_id_map.get(order_index)
    
    if not order_id: 
        query.answer("❌ Order info expired, please check purchase history again" if lang == 'en' else "❌ 订单信息已过期，请重新查看购买记录", show_alert=True)
        return
    
    # 获取订单信息
    order = agent_orders.find_one({
        'order_id': order_id,
        'customer_id': user_id,
        'agent_bot_id': AGENT_BOT_ID
    })
    
    if not order:
        query.answer("❌ Order not found" if lang == 'en' else "❌ 订单不存在", show_alert=True)
        return
    
    product_name = order.get('product_name', '')
    display_product = t(product_name, lang) if lang == 'en' else product_name
    quantity = order.get('quantity', 0)
    nowuid = order.get('original_nowuid', '')
    delivery_type = order.get('delivery_type', '协议号')
    
    try:
        # 发送提示消息
        if lang == 'en':
            context.bot.send_message(
                chat_id=user_id,
                text=f"📦 Preparing order files...\n\nProduct: {display_product}\nQuantity: {quantity}"
            )
        else:
            context.bot.send_message(
                chat_id=user_id,
                text=f"📦 正在为您准备订单文件...\n\n商品：{display_product}\n数量：{quantity}"
            )
        
        if delivery_type == '协议号':
            # 协议号类型：需要打包发送
            # 从hb集合中获取该订单购买的账号
            accounts = list(hb.find({
                'nowuid': nowuid,
                'gmid': user_id,
                'state': 1
            }).limit(quantity))
            
            if len(accounts) < quantity:
                context.bot.send_message(
                    chat_id=user_id,
                    text="⚠️ Some files may be lost, please contact customer service" if lang == 'en' else "⚠️ 部分文件可能已丢失，请联系客服"
                )
                # 即使部分丢失，也尝试发送找到的
            
            if accounts:
                # 获取账号文件名
                folder_names = [doc['projectname'] for doc in accounts]
                
                # 创建zip文件
                timestamp = int(time.time())
                zip_filename = f"./协议号发货/{user_id}_{timestamp}_redownload.zip"
                
                # 确保目录存在
                os.makedirs('./协议号发货', exist_ok=True)
                
                # 打包文件
                with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for file_name in folder_names:
                        # 尝试总部路径和本地路径
                        json_file = os.path.join(BASE_PROTOCOL_PATH, nowuid, file_name + ".json")
                        session_file = os.path.join(BASE_PROTOCOL_PATH, nowuid, file_name + ".session")
                        
                        if not os.path.exists(json_file):
                            json_file = os.path.join(FALLBACK_PROTOCOL_PATH, nowuid, file_name + ".json")
                        if not os.path.exists(session_file):
                            session_file = os.path.join(FALLBACK_PROTOCOL_PATH, nowuid, file_name + ".session")
                        
                        if os.path.exists(json_file):
                            zipf.write(json_file, os.path.basename(json_file))
                        if os.path.exists(session_file):
                            zipf.write(session_file, os.path.basename(session_file))
                
                # 发送文件
                with open(zip_filename, "rb") as f:
                    if lang == 'en':
                        caption = f"✅ Order files downloaded\n\nProduct: {display_product}\nQuantity: {len(accounts)}"
                    else: 
                        caption = f"✅ 订单文件下载完成\n\n商品：{display_product}\n数量：{len(accounts)}"
                    context.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption=caption
                    )
                
                # 清理临时文件
                try:
                    os.remove(zip_filename)
                except (OSError, FileNotFoundError) as e:
                    logging.warning(f"清理临时文件失败:  {e}")
            else:
                context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Order files not found, please contact customer service" if lang == 'en' else "❌ 未找到订单文件，请联系客服"
                )
        else:
            # 其他类型：发送文本内容
            accounts = list(hb.find({
                'nowuid': nowuid,
                'gmid': user_id,
                'state': 1
            }).limit(quantity))
            
            if accounts:
                content_list = []
                for account in accounts: 
                    content_list.append(account.get('hbid', ''))
                
                content = '\n'.join(content_list)
                
                if lang == 'en':
                    context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ <b>Order Content</b>\n\n📦 Product: {display_product}\n📊 Quantity: {len(accounts)}\n\n📝 Content:\n<code>{content}</code>",
                        parse_mode='HTML'
                    )
                else:
                    context.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ <b>订单内容</b>\n\n📦 商品：{display_product}\n📊 数量：{len(accounts)}\n\n📝 内容：\n<code>{content}</code>",
                        parse_mode='HTML'
                    )
            else:
                context.bot.send_message(
                    chat_id=user_id,
                    text="❌ Order content not found, please contact customer service" if lang == 'en' else "❌ 未找到订单内容，请联系客服"
                )
        
        logging.info(f"✅ 用户 {user_id} 重新下载订单: {order_id}")
        
    except Exception as e:
        logging.error(f"❌ 下载订单失败: {e}")
        import traceback
        traceback.print_exc()
        context.bot.send_message(
            chat_id=user_id,
            text="❌ 下载失败，请联系客服"
        )


def back_to_main(update: Update, context: CallbackContext):
    """返回主菜单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    fullname = query.from_user.full_name.replace('<', '').replace('>', '')
    
    # 获取用户信息
    agent_user = get_agent_bot_user(AGENT_BOT_ID, user_id)
    balance = agent_user.get('USDT', 0) if agent_user else 0
    total_purchases = agent_user.get('zgsl', 0) if agent_user else 0
    creation_time = agent_user.get('creation_time', '') if agent_user else ''
    lang = agent_user.get('lang', 'zh') if agent_user else 'zh'
    
    # 截取日期部分
    registration_date = creation_time[:10] if creation_time else ('未知' if lang == 'zh' else 'Unknown')
    
    # 获取问候语
    greeting = get_time_greeting()
    
    # 构建欢迎消息
    welcome_text = ""
    
    # 如果配置了Bot名称和标语，显示它们
    if BOT_NAME or BOT_SLOGAN: 
        if BOT_NAME:
            welcome_text += f"          <b>{BOT_NAME}</b>\n"
        if BOT_SLOGAN: 
            welcome_text += f"   {BOT_SLOGAN}\n"
        welcome_text += "\n"
    
    # 问候和用户信息
    if lang == 'zh':
        welcome_text += f"👋 {greeting}，{fullname}\n\n"
        welcome_text += f"🆔 <b>用户ID：<code>{user_id}</code></b>\n"
        welcome_text += f"📅 <b>注册时间：{registration_date}</b>\n\n"
        welcome_text += f"💰 <b>账户余额：{balance:.2f}</b>\n"
        welcome_text += f"✅ <b>总购买数量：{total_purchases}\n</b>"
    else: 
        welcome_text += f"👋 {t(greeting, lang)}, {fullname}\n\n"
        welcome_text += f"🆔 <b>User ID:  <code>{user_id}</code></b>\n"
        welcome_text += f"📅 <b>Registered:  {registration_date}</b>\n\n"
        welcome_text += f"💰 <b>Balance: {balance:.2f}</b>\n"
        welcome_text += f"✅ <b>Total Purchases: {total_purchases}\n</b>"
    
    # 分隔线
    welcome_text += "\n" + "➖" * 10 + "\n"
    
    # 永久用户名和通知群
    if PERMANENT_USERNAME: 
        if lang == 'zh':
            welcome_text += f"👤 <b>永久用户名：{PERMANENT_USERNAME}</b>\n"
        else: 
            welcome_text += f"👤 <b>Permanent Username: {PERMANENT_USERNAME}</b>\n"
    if NOTIFICATION_GROUP: 
        if lang == 'zh':
            welcome_text += f"📢 <b>补货通知群：{NOTIFICATION_GROUP}</b>\n"
        else:
            welcome_text += f"📢 <b>Notification Group:  {NOTIFICATION_GROUP}</b>\n"
    
    # 2列网格按钮布局
    if lang == 'zh':
        keyboard = [
            [
                InlineKeyboardButton("📋 账号列表", callback_data="product_list"),
                InlineKeyboardButton("💰 充值余额", callback_data="recharge")
            ],
            [
                InlineKeyboardButton("📖 购买须知", callback_data="purchase_notice"),
                InlineKeyboardButton("📝 购买记录", callback_data="purchase_history")
            ],
            [
                InlineKeyboardButton("🌍 区号搜索", callback_data="country_search"),
                InlineKeyboardButton("🌐 My Language", callback_data="switch_lang")
            ]
        ]
    else: 
        keyboard = [
            [
                InlineKeyboardButton("📋 Account List", callback_data="product_list"),
                InlineKeyboardButton("💰 Recharge", callback_data="recharge")
            ],
            [
                InlineKeyboardButton("📖 Purchase Notice", callback_data="purchase_notice"),
                InlineKeyboardButton("📝 Purchase History", callback_data="purchase_history")
            ],
            [
                InlineKeyboardButton("🌍 Country Search", callback_data="country_search"),
                InlineKeyboardButton("🌐 My Language", callback_data="switch_lang")
            ]
        ]
    
    # 删除原消息并发送新的媒体消息（兼容不同媒体类型）
    try:
        query.message.delete()
    except Exception as e:
        logging.debug(f"删除消息失败（预期行为）: {e}")
    
    send_media_message(
        context=context,
        chat_id=user_id,
        media_url=BANNER_IMAGE_URL,
        caption=welcome_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ===================== 管理面板功能 =====================

@require_admin
def admin_command(update: Update, context: CallbackContext):
    """处理/admin命令 - 显示管理面板"""
    show_admin_panel(update, context, is_command=True)


def show_admin_panel(update: Update, context: CallbackContext, is_command: bool = False):
    """显示管理面板主界面"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        error_msg = "❌ 无权限访问"
        if not ADMIN_IDS:
            error_msg += "\n\n⚠️ 系统未配置管理员\n请联系系统管理员在配置文件中添加 ADMIN_IDS"
        else:
            error_msg += f"\n\n您的ID: {user_id}\n请联系系统管理员添加到管理员列表"
        
        if is_command:
            update.message.reply_text(error_msg)
        else:
            update.callback_query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 获取今日统计数据
    from datetime import datetime, timedelta
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 统计今日订单
    today_orders = list(agent_orders.find({
        'agent_bot_id': AGENT_BOT_ID,
        'order_time': {'$gte': format_beijing_time(today_start)}
    }))
    
    today_order_count = len(today_orders)
    today_sales = sum(order.get('total_price', 0) for order in today_orders)
    today_profit = sum(order.get('profit', 0) for order in today_orders)
    
    # 获取可提现余额
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    available_balance = agent_info.get('available_balance', 0) if agent_info else 0
    
    text = f"""
🤖 <b>代理管理面板</b>

📊 <b>今日数据</b>
├─ 订单数：{today_order_count} 单
├─ 销售额：{today_sales:.2f} USDT
└─ 利润：{today_profit:.2f} USDT

💰 可提现余额：{available_balance:.2f} USDT
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("👥 用户列表", callback_data="admin_users"),
            InlineKeyboardButton("📊 销售统计", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("💸 申请提现", callback_data="admin_withdraw"),
            InlineKeyboardButton("📦 商品库存", callback_data="admin_inventory")
        ],
        [InlineKeyboardButton("📢 用户私信", callback_data="agent_sifa")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_main")]
    ]
    
    if is_command:
        update.message.reply_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        query = update.callback_query
        query.answer()
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# ==================== 1.用户列表 ====================

def show_admin_users(update: Update, context: CallbackContext):
    """显示用户列表主界面"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 获取用户统计
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    total_users = agent_users.count_documents({})
    
    # 今日新增用户
    from datetime import datetime
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_new_users = agent_users.count_documents({
        'creation_time': {'$gte': format_beijing_time(today_start)}
    })
    
    # 活跃用户（今日有订单）
    today_orders = agent_orders.find({
        'agent_bot_id': AGENT_BOT_ID,
        'order_time': {'$gte': format_beijing_time(today_start)}
    })
    active_user_ids = set(order.get('user_id') for order in today_orders)
    active_users = len(active_user_ids)
    
    text = f"""
👥 <b>用户列表</b>

📊 <b>用户概览</b>
├─ 总用户数：{total_users} 人
├─ 今日新增：{today_new_users} 人
└─ 活跃用户：{active_users} 人

🔍 筛选方式：
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("全部用户", callback_data="admin_users_filter_all_1"),
            InlineKeyboardButton("今日新增", callback_data="admin_users_filter_today_1")
        ],
        [
            InlineKeyboardButton("有余额用户", callback_data="admin_users_filter_balance_1"),
            InlineKeyboardButton("有订单用户", callback_data="admin_users_filter_orders_1")
        ],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_admin_users_list(update: Update, context: CallbackContext):
    """显示用户列表（分页）"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 解析callback_data: admin_users_filter_{filter_type}_{page}
    parts = query.data.split('_')
    filter_type = parts[3]
    page = int(parts[4]) if len(parts) > 4 else 1
    
    per_page = 10
    skip = (page - 1) * per_page
    
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    
    # 根据筛选条件获取用户
    from datetime import datetime
    if filter_type == 'all':
        filter_query = {}
        filter_name = "全部用户"
    elif filter_type == 'today':
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        filter_query = {'creation_time': {'$gte': format_beijing_time(today_start)}}
        filter_name = "今日新增"
    elif filter_type == 'balance':
        filter_query = {'USDT': {'$gt': 0}}
        filter_name = "有余额用户"
    elif filter_type == 'orders':
        # 获取有订单的用户ID
        order_user_ids = agent_orders.distinct('user_id', {'agent_bot_id': AGENT_BOT_ID})
        filter_query = {'user_id': {'$in': order_user_ids}}
        filter_name = "有订单用户"
    else:
        filter_query = {}
        filter_name = "全部用户"
    
    total_count = agent_users.count_documents(filter_query)
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    
    users = list(agent_users.find(filter_query).sort('creation_time', -1).skip(skip).limit(per_page))
    
    if not users:
        text = f"👥 {filter_name}\n\n暂无用户"
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_users")]]
    else:
        text = f"👥 <b>{filter_name}</b> (第{page}页/共{total_pages}页)\n\n"
        
        for i, user in enumerate(users, 1):
            user_id = user.get('user_id', 0)
            username = user.get('username', '')
            balance = user.get('USDT', 0)
            order_count = user.get('zgsl', 0)
            creation_time = user.get('creation_time', '')
            
            # 截取日期部分
            if len(creation_time) > 10:
                creation_time = creation_time[:10]
            
            text += f"{skip + i}.用户ID: {user_id}\n"
            if username:
                text += f"   👤 @{username}\n"
            text += f"   💰 余额: {balance:.2f} USDT\n"
            text += f"   📦 订单: {order_count} 单\n"
            text += f"   📅 注册: {creation_time}\n\n"
        
        keyboard = []
        
        # 分页按钮
        page_buttons = []
        if page > 1:
            page_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_users_filter_{filter_type}_{page-1}"))
        if page < total_pages:
            page_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"admin_users_filter_{filter_type}_{page+1}"))
        
        if page_buttons:
            keyboard.append(page_buttons)
        
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_users")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================== 2.销售统计 ====================

def show_admin_stats(update: Update, context: CallbackContext):
    """显示销售统计主界面"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    text = """
📊 <b>销售统计</b>

📅 选择时间范围：
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("今日", callback_data="admin_stats_today"),
            InlineKeyboardButton("昨日", callback_data="admin_stats_yesterday"),
            InlineKeyboardButton("本周", callback_data="admin_stats_week")
        ],
        [
            InlineKeyboardButton("本月", callback_data="admin_stats_month"),
            InlineKeyboardButton("全部", callback_data="admin_stats_all")
        ],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_admin_stats_detail(update: Update, context: CallbackContext):
    """显示统计详情"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 解析时间范围
    from datetime import datetime, timedelta
    time_range = query.data.replace('admin_stats_', '')
    
    now = get_beijing_now()
    
    if time_range == 'today':
        start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now
        range_name = "今日"
        date_str = start_time.strftime('%Y-%m-%d')
    elif time_range == 'yesterday':
        start_time = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        range_name = "昨日"
        date_str = start_time.strftime('%Y-%m-%d')
    elif time_range == 'week':
        start_time = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = now
        range_name = "本周"
        date_str = f"{start_time.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}"
    elif time_range == 'month':
        start_time = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = now
        range_name = "本月"
        date_str = now.strftime('%Y年%m月')
    else:  # all
        start_time = datetime(2020, 1, 1)
        end_time = now
        range_name = "全部时间"
        date_str = "所有记录"
    
    # 获取订单数据
    orders = list(agent_orders.find({
        'agent_bot_id': AGENT_BOT_ID,
        'order_time': {
            '$gte': format_beijing_time(start_time),
            '$lte': format_beijing_time(end_time)
        }
    }))
    
    order_count = len(orders)
    total_sales = sum(order.get('total_price', 0) for order in orders)
    total_cost = sum(order.get('cost', 0) for order in orders)
    total_profit = sum(order.get('profit', 0) for order in orders)
    
    # 统计商品销量
    product_sales = {}
    for order in orders:
        product_name = order.get('product_name', '未知商品')
        quantity = order.get('quantity', 0)
        profit = order.get('profit', 0)
        
        if product_name not in product_sales:
            product_sales[product_name] = {'quantity': 0, 'profit': 0}
        
        product_sales[product_name]['quantity'] += quantity
        product_sales[product_name]['profit'] += profit
    
    # 排序商品销量
    sorted_products = sorted(product_sales.items(), key=lambda x: x[1]['quantity'], reverse=True)
    
    # 统计用户数据
    order_user_ids = set(order.get('user_id') for order in orders)
    ordering_users = len(order_user_ids)
    
    # 新增用户
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    new_users = agent_users.count_documents({
        'creation_time': {
            '$gte': format_beijing_time(start_time),
            '$lte': format_beijing_time(end_time)
        }
    })
    
    text = f"""
📊 <b>{range_name}销售统计</b>

📅 日期：{date_str}

💰 <b>销售数据</b>
├─ 订单数量：{order_count} 单
├─ 销售总额：{total_sales:.2f} USDT
├─ 成本支出：{total_cost:.2f} USDT
└─ 净利润：{total_profit:.2f} USDT

📦 <b>商品销量排行</b>
"""
    
    for i, (product_name, stats) in enumerate(sorted_products[:5], 1):
        text += f"{i}.{product_name} - {stats['quantity']}个 (利润: {stats['profit']:.2f})\n"
    
    text += f"""
👥 <b>用户数据</b>
├─ 下单用户：{ordering_users} 人
└─ 新增用户：{new_users} 人
    """.strip()
    
    keyboard = [
        [InlineKeyboardButton("🔄 刷新", callback_data=f"admin_stats_{time_range}")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_stats")]
    ]
    
    try:
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception:
        query.answer("📊 数据已是最新", show_alert=False)


# ==================== 3.申请提现 ====================

def show_admin_withdraw(update: Update, context: CallbackContext):
    """显示提现中心"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 获取代理信息
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    
    total_commission = agent_info.get('total_commission', 0) if agent_info else 0
    withdrawn = agent_info.get('total_withdrawn', 0) if agent_info else 0
    available_balance = agent_info.get('available_balance', 0) if agent_info else 0
    
    # 计算待审核金额
    pending_withdrawals = list(agent_withdrawals.find({
        'agent_bot_id': AGENT_BOT_ID,
        'status': 'pending'
    }))
    pending_amount = sum(w.get('amount', 0) for w in pending_withdrawals)
    
    text = f"""
💸 <b>提现中心</b>

💰 <b>账户余额</b>
├─ 累计利润：{total_commission:.2f} USDT
├─ 已提现：{withdrawn:.2f} USDT
├─ 待审核：{pending_amount:.2f} USDT
└─ 可提现：{available_balance:.2f} USDT

📋 <b>提现说明</b>
• 最低提现：10 USDT
• 手续费：0%
• 审核时间：24小时内
    """.strip()
    
    keyboard = []
    
    if available_balance >= 10:
        keyboard.append([InlineKeyboardButton("💵 申请提现", callback_data="admin_withdraw_apply")])
    else:
        keyboard.append([InlineKeyboardButton("💵 余额不足10U", callback_data="admin_withdraw_insufficient")])
    
    keyboard.append([InlineKeyboardButton("📋 提现记录", callback_data="admin_withdraw_records_1")])
    keyboard.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_admin_withdraw_apply(update: Update, context: CallbackContext):
    """申请提现 - 检查地址绑定并引导输入金额"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    user_id = query.from_user.id
    
    # 获取代理信息
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    available_balance = agent_info.get('available_balance', 0) if agent_info else 0
    wallet_address = agent_info.get('wallet_address', '') if agent_info else ''
    
    if available_balance < 10:
        query.answer("余额不足10 USDT", show_alert=True)
        return
    
    # 检查是否已绑定地址
    if not wallet_address:
        # 未绑定地址，提示输入
        text = f"""
💰 <b>申请提现</b>

💵 可提现金额：{available_balance:.2f} USDT

⚠️ <b>您还未绑定收款地址</b>
请输入您的 TRC20 收款地址：

💡 地址格式：T开头，34位字符
⚠️ 地址绑定后如需修改请联系管理员
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("❌ 取消", callback_data="admin_withdraw")]
        ]
        
        # 设置状态，等待地址输入
        context.user_data['waiting_for_withdraw_address'] = True
        context.user_data['withdraw_address_binding'] = True
    else:
        # 已绑定地址，显示地址并提示输入金额
        # 显示地址简写
        address_display = f"{wallet_address[:6]}...{wallet_address[-4:]}"
        
        text = f"""
💰 <b>申请提现</b>

💵 可提现金额：{available_balance:.2f} USDT
💳 收款地址：<code>{address_display}</code>

📝 请输入提现金额（最低 10 USDT）：

发送 /cancel 取消操作
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("❌ 取消", callback_data="admin_withdraw")]
        ]
        
        # 设置状态，等待金额输入
        context.user_data['waiting_for_withdraw_amount'] = True
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def handle_withdraw_amount(update: Update, context: CallbackContext):
    """处理提现金额选择"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 解析金额
    amount_str = query.data.replace('admin_withdraw_amount_', '')
    try:
        amount = float(amount_str)
    except ValueError:
        query.answer("金额格式错误", show_alert=True)
        return
    
    # 验证金额
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    available_balance = agent_info.get('available_balance', 0) if agent_info else 0
    
    if amount > available_balance:
        query.answer("提现金额超过可用余额", show_alert=True)
        return
    
    if amount < 10:
        query.answer("最低提现金额为10 USDT", show_alert=True)
        return
    
    # 存储金额到context
    context.user_data['withdraw_amount'] = amount
    
    text = f"""
📍 <b>请输入收款地址</b>

网络：TRC20 (USDT)

💵 提现金额：{amount:.2f} USDT

请发送您的TRC20钱包地址：
    """.strip()
    
    keyboard = [
        [InlineKeyboardButton("🔙 取消", callback_data="admin_withdraw")]
    ]
    
    # 设置状态，等待地址输入
    context.user_data['waiting_for_withdraw_address'] = True
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )




def handle_address_binding(update: Update, context: CallbackContext, address: str):
    """处理地址绑定"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        update.message.reply_text("❌ 无权限访问")
        return
    
    # 获取代理信息
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    available_balance = agent_info.get('available_balance', 0) if agent_info else 0
    
    # 显示确认界面
    text = f"""
💳 <b>确认绑定收款地址</b>

📍 收款地址：
<code>{address}</code>

⚠️ <b>重要提示：</b>
• 地址绑定后您将<b>无法自行修改</b>
• 如需修改，请联系总部管理员
• 请务必确认地址正确无误

确认绑定此地址吗？
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("❌ 取消", callback_data="admin_withdraw"),
            InlineKeyboardButton("✅ 确认绑定", callback_data=f"admin_withdraw_bind_address")
        ]
    ]
    
    # 存储地址到context
    context.user_data['withdraw_address'] = address
    
    # 清除等待状态
    context.user_data.pop('waiting_for_withdraw_address', None)
    context.user_data.pop('withdraw_address_binding', None)
    
    update.message.reply_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def handle_withdraw_amount_input(update: Update, context: CallbackContext, amount_str: str):
    """处理用户输入的提现金额"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        update.message.reply_text("❌ 无权限访问")
        return
    
    # 验证金额格式
    try:
        amount = float(amount_str)
    except ValueError:
        update.message.reply_text(
            "❌ 金额格式错误，请输入数字\n"
            "示例：50 或 50.5"
        )
        return
    
    # 验证金额范围
    if amount < 10:
        update.message.reply_text(
            "❌ 提现金额不能低于 10 USDT\n"
            "请重新输入金额"
        )
        return
    
    # 获取可用余额
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    available_balance = agent_info.get('available_balance', 0) if agent_info else 0
    wallet_address = agent_info.get('wallet_address', '') if agent_info else ''
    
    if amount > available_balance:
        update.message.reply_text(
            f"❌ 提现金额超过可用余额\n\n"
            f"可用余额：{available_balance:.2f} USDT\n"
            f"请求金额：{amount:.2f} USDT\n\n"
            f"请重新输入金额"
        )
        return
    
    # 计算提现后余额
    new_balance = available_balance - amount
    
    # 显示地址简写
    address_display = f"{wallet_address[:6]}...{wallet_address[-4:]}"
    
    # 显示确认界面
    text = f"""
💰 <b>确认提现</b>

💵 提现金额：{amount:.2f} USDT
💰 当前余额：{available_balance:.2f} USDT
💰 提现后余额：{new_balance:.2f} USDT
💳 收款地址：<code>{address_display}</code>

确认提交提现申请吗？
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("❌ 取消", callback_data="admin_withdraw"),
            InlineKeyboardButton("✅ 确认提现", callback_data=f"admin_withdraw_confirm_final")
        ]
    ]
    
    # 存储金额到context
    context.user_data['withdraw_amount'] = amount
    
    # 清除等待状态
    context.user_data.pop('waiting_for_withdraw_amount', None)
    
    update.message.reply_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def confirm_withdraw(update: Update, context: CallbackContext, address: str):
    """确认提现"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        update.message.reply_text("❌ 无权限访问")
        return
    
    amount = context.user_data.get('withdraw_amount', 0)
    
    if amount < 10:
        update.message.reply_text("提现金额错误，请重新申请")
        return
    
    text = f"""
💸 <b>确认提现申请</b>

💵 提现金额：{amount:.2f} USDT
📍 收款地址：
<code>{address}</code>

⚠️ 请仔细核对地址，提交后无法修改！
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("❌ 取消", callback_data="admin_withdraw"),
            InlineKeyboardButton("✅ 确认提交", callback_data=f"admin_withdraw_confirm")
        ]
    ]
    
    # 存储地址到context（避免callback_data长度限制）
    context.user_data['withdraw_address'] = address
    
    update.message.reply_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    # 清除等待状态
    context.user_data.pop('waiting_for_withdraw_address', None)


def bind_wallet_address(update: Update, context: CallbackContext):
    """确认绑定钱包地址"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 从context获取地址
    address = context.user_data.get('withdraw_address', '')
    
    if not address or not address.startswith('T') or len(address) != 34:
        query.answer("地址信息错误，请重新操作", show_alert=True)
        return
    
    # 绑定地址到代理账户
    try:
        apply_time = beijing_now_str()  # 使用北京时间
        agent_bots.update_one(
            {'agent_bot_id': AGENT_BOT_ID},
            {
                '$set': {
                    'wallet_address': address,
                    'wallet_address_bind_time': apply_time
                }
            }
        )
        
        # 清除context中的临时数据
        context.user_data.pop('withdraw_address', None)
        
        # 获取可用余额
        agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
        available_balance = agent_info.get('available_balance', 0) if agent_info else 0
        
        # 显示地址简写
        address_display = f"{address[:6]}...{address[-4:]}"
        
        text = f"""
✅ <b>地址绑定成功</b>

💳 收款地址：<code>{address_display}</code>
⏰ 绑定时间：{apply_time}

💰 可提现金额：{available_balance:.2f} USDT

📝 请输入提现金额（最低 10 USDT）：

发送 /cancel 取消操作
        """.strip()
        
        keyboard = [
            [InlineKeyboardButton("❌ 取消", callback_data="admin_withdraw")]
        ]
        
        # 设置状态，等待金额输入
        context.user_data['waiting_for_withdraw_amount'] = True
        
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        logging.info(f"✅ 代理绑定钱包地址成功: agent_bot_id={AGENT_BOT_ID}, address={address}")
        
    except Exception as e:
        logging.error(f"❌ 绑定钱包地址失败: {e}")
        query.answer("系统错误，请稍后重试", show_alert=True)


def submit_withdraw(update: Update, context: CallbackContext):
    """提交提现申请"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 获取代理信息以获取绑定的地址
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    if not agent_info:
        query.answer("系统错误，代理信息不存在", show_alert=True)
        return
    
    # 从context获取金额，从数据库获取地址
    amount = context.user_data.get('withdraw_amount', 0)
    address = context.user_data.get('withdraw_address', '') or agent_info.get('wallet_address', '')
    
    if not address or amount < 10:
        query.answer("提现信息错误，请重新申请", show_alert=True)
        return
    
    # 使用原子操作更新余额并验证
    from datetime import datetime
    import uuid
    
    # 生成唯一提现单号（使用北京时间）
    from mongo import get_beijing_now
    beijing_time = get_beijing_now()
    withdrawal_id = f"W{beijing_time.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
    apply_time = beijing_now_str()  # 使用北京时间
    
    # 原子操作：检查余额并扣除
    result = agent_bots.find_one_and_update(
        {
            'agent_bot_id': AGENT_BOT_ID,
            'available_balance': {'$gte': amount}  # 确保余额充足
        },
        {
            '$inc': {'available_balance': -amount},
            '$set': {'last_update': apply_time}
        },
        return_document=True
    )
    
    if not result:
        query.answer("余额不足或状态已变更，请刷新后重试", show_alert=True)
        # 清除用户数据
        context.user_data.pop('withdraw_amount', None)
        context.user_data.pop('withdraw_address', None)
        return
    
    # 获取代理信息（用于通知）
    agent_info = agent_bots.find_one({'agent_bot_id': AGENT_BOT_ID})
    
    # 创建提现记录
    try:
        agent_withdrawals.insert_one({
            'withdrawal_id': withdrawal_id,
            'agent_bot_id': AGENT_BOT_ID,
            'agent_name': AGENT_NAME,
            'amount': amount,
            'address': address,
            'status': 'pending',
            'apply_time': apply_time,
            'process_time': '',
            'txid': '',
            'remark': ''
        })
    except Exception as e:
        logging.error(f"❌ 创建提现记录失败: {e}")
        # 回滚余额扣除
        agent_bots.update_one(
            {'agent_bot_id': AGENT_BOT_ID},
            {'$inc': {'available_balance': amount}}
        )
        query.answer("系统错误，请稍后重试", show_alert=True)
        return
    
    # 发送通知到 AGENT_ORDER_NOTIFY_GROUP
    if AGENT_ORDER_NOTIFY_GROUP and AGENT_ORDER_NOTIFY_GROUP.strip():
        notify_text = f"""
🔔 <b>新提现申请</b>

👤 代理商：{agent_info.get('agent_name', 'Unknown') if agent_info else 'Unknown'}
🆔 代理ID：{AGENT_BOT_ID}
📋 订单号：<code>{withdrawal_id}</code>
💵 金额：<b>{amount:.2f} USDT</b>
💳 地址：<code>{address}</code>
⏰ 时间：{apply_time}
📊 状态：待处理
        """.strip()
        try:
            group_id = int(AGENT_ORDER_NOTIFY_GROUP)
            context.bot.send_message(
                chat_id=group_id,
                text=notify_text,
                parse_mode='HTML'
            )
            logging.info(f"✅ 提现通知已发送到订单群")
        except ValueError as e:
            logging.error(f"❌ 订单群ID格式错误: {e}")
        except Exception as e:
            logging.error(f"❌ 发送提现通知失败: {e}")
    
    # 清除用户数据
    context.user_data.pop('withdraw_amount', None)
    context.user_data.pop('withdraw_address', None)
    
    # 显示地址简写
    address_display = f"{address[:6]}...{address[-4:]}"
    
    text = f"""
✅ <b>提现申请已提交</b>

📋 订单号：<code>{withdrawal_id}</code>
💵 提现金额：{amount:.2f} USDT
💳 收款地址：<code>{address_display}</code>
📊 状态：待处理

⏰ 预计 24 小时内处理完成
如有问题请联系总部客服
    """.strip()    
    keyboard = [
        [InlineKeyboardButton("📋 查看提现记录", callback_data="admin_withdraw_records_1")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_withdraw")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    logging.info(f"✅ 提现申请提交: agent={AGENT_BOT_ID}, id={withdrawal_id}, amount={amount}, address={address}")



def show_withdraw_records(update: Update, context: CallbackContext):
    """显示提现记录"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 解析页码
    page = int(query.data.replace('admin_withdraw_records_', ''))
    per_page = 5
    skip = (page - 1) * per_page
    
    # 获取提现记录
    total_count = agent_withdrawals.count_documents({'agent_bot_id': AGENT_BOT_ID})
    records = list(
        agent_withdrawals.find({'agent_bot_id': AGENT_BOT_ID})
        .sort('apply_time', -1)
        .skip(skip)
        .limit(per_page)
    )
    
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    
    if not records:
        text = "📋 <b>提现记录</b>\n\n暂无提现记录"
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_withdraw")]]
    else:
        text = f"📋 <b>提现记录</b> (第{page}页/共{total_pages}页)\n\n"
        
        for i, record in enumerate(records, 1):
            amount = record.get('amount', 0)
            apply_time = record.get('apply_time', '')
            status = record.get('status', 'pending')
            txid = record.get('txid', '')
            
            # 截取时间
            if len(apply_time) > 16:
                apply_time = apply_time[:16]
            
            status_emoji = {
                'pending': '⏳',
                'approved': '✅',
                'completed': '✅',
                'rejected': '❌'
            }.get(status, '❓')
            
            status_text = {
                'pending': '待审核',
                'approved': '已批准',
                'completed': '已完成',
                'rejected': '已拒绝'
            }.get(status, '未知')
            
            text += f"{i}.💵 {amount:.2f} USDT\n"
            text += f"   📅 {apply_time}\n"
            text += f"   {status_emoji} 状态：{status_text}\n"
            
            if txid:
                # 截取txid
                short_txid = txid[:8] + '...' if len(txid) > 8 else txid
                text += f"   🔗 TxID: {short_txid}\n"
            
            text += "\n"
        
        keyboard = []
        
        # 分页按钮
        page_buttons = []
        if page > 1:
            page_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_withdraw_records_{page-1}"))
        if page < total_pages:
            page_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"admin_withdraw_records_{page+1}"))
        
        if page_buttons:
            keyboard.append(page_buttons)
        
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_withdraw")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================== 4.商品库存 ====================

def show_admin_inventory(update: Update, context: CallbackContext):
    """显示商品库存主界面"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 统计库存概览
    total_products = ejfl.count_documents({})
    
    # 统计总库存
    total_stock = 0
    out_of_stock = 0
    
    for product in ejfl.find({}):
        nowuid = product.get('nowuid')
        stock = get_real_time_stock(nowuid)
        total_stock += stock
        if stock == 0:
            out_of_stock += 1
    
    text = f"""
📦 <b>商品库存</b>

📊 <b>库存概览</b>
├─ 商品种类：{total_products} 种
├─ 总库存：{total_stock} 个
└─ 缺货商品：{out_of_stock} 种

🔍 筛选：
    """.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("全部商品", callback_data="admin_inventory_filter_all_1"),
            InlineKeyboardButton("有库存", callback_data="admin_inventory_filter_instock_1")
        ],
        [
            InlineKeyboardButton("缺货", callback_data="admin_inventory_filter_outstock_1")
        ],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def show_admin_inventory_list(update: Update, context: CallbackContext):
    """显示商品库存列表"""
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 解析callback_data: admin_inventory_filter_{filter_type}_{page}
    parts = query.data.split('_')
    filter_type = parts[3]
    page = int(parts[4]) if len(parts) > 4 else 1
    
    per_page = 10
    skip = (page - 1) * per_page
    
    # 获取所有商品
    all_products = list(ejfl.find({}).sort('row', 1))
    
    # 根据筛选条件过滤
    filtered_products = []
    
    for product in all_products:
        nowuid = product.get('nowuid')
        stock = get_real_time_stock(nowuid)
        
        if filter_type == 'all':
            filtered_products.append((product, stock))
        elif filter_type == 'instock' and stock > 0:
            filtered_products.append((product, stock))
        elif filter_type == 'outstock' and stock == 0:
            filtered_products.append((product, stock))
    
    filter_names = {
        'all': '全部商品',
        'instock': '有库存',
        'outstock': '缺货商品'
    }
    filter_name = filter_names.get(filter_type, '全部商品')
    
    total_count = len(filtered_products)
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    
    # 分页
    products_page = filtered_products[skip:skip + per_page]
    
    if not products_page:
        text = f"📦 {filter_name}\n\n暂无商品"
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_inventory")]]
    else:
        text = f"📦 <b>{filter_name}</b> (第{page}页/共{total_pages}页)\n\n"
        
        # 按分类分组
        current_category = None
        
        for product, stock in products_page:
            uid = product.get('uid')
            category = fenlei.find_one({'uid': uid})
            category_name = category.get('projectname', '未知分类') if category else '未知分类'
            
            # 如果分类变化，显示分类标题
            if category_name != current_category:
                text += f"\n📂 <b>{category_name}</b>\n\n"
                current_category = category_name
            
            product_name = product.get('projectname', '未知商品')
            hq_price = float(product.get('money', 0))
            agent_price = hq_price * (1 + COMMISSION_RATE)
            
            # 获取已售数量
            nowuid = product.get('nowuid')
            sold_count = agent_orders.count_documents({
                'agent_bot_id': AGENT_BOT_ID,
                'product_id': nowuid
            })
            
            text += f"• {product_name}\n"
            text += f"  💰 成本: {hq_price:.2f} | 售价: {agent_price:.2f}\n"
            
            if stock > 0:
                text += f"  📦 库存: {stock} 个\n"
            else:
                text += f"  ⚠️ 库存: 0 个 (缺货)\n"
            
            text += f"  📈 已售: {sold_count} 个\n\n"
        
        keyboard = []
        
        # 分页按钮
        page_buttons = []
        if page > 1:
            page_buttons.append(InlineKeyboardButton("⬅️ 上一页", 
                                                     callback_data=f"admin_inventory_filter_{filter_type}_{page-1}"))
        if page < total_pages:
            page_buttons.append(InlineKeyboardButton("下一页 ➡️", 
                                                     callback_data=f"admin_inventory_filter_{filter_type}_{page+1}"))
        
        if page_buttons:
            keyboard.append(page_buttons)
        
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_inventory")])
    
    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==================== 用户私信广播功能 ====================

def parse_url(content):
    """解析单个按钮格式：名称&链接"""
    args = content.split('&')
    if len(args) < 2:
        return [InlineKeyboardButton("格式错误，点击联系管理员", url="https://www.baidu.com")]
    else:
        title = args[0].strip()
        url = args[1].strip() if len(args) >= 2 else None
        return [InlineKeyboardButton(title, url=url)]


def parse_urls(content, maxurl=99):
    """解析多个按钮：按钮名称|链接（每行一个）"""
    cnt_url = 0
    keyboard = []
    rows = content.split('\n')
    for row in rows:
        krow = []
        els = row.split('|')
        for el in els:
            kel = parse_url(el)
            if not kel:
                continue
            krow = krow + kel
            cnt_url = cnt_url + 1
            if cnt_url == maxurl:
                break
        keyboard.append(krow)
        if cnt_url == maxurl:
            break
    return keyboard


def agent_sifa(update: Update, context: CallbackContext):
    """用户私信主菜单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 权限检查
    if not is_admin(user_id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 确保配置存在
    fqdtw_list = sftw.find_one({'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'})
    if fqdtw_list is None:
        sifatuwen(AGENT_BOT_ID, '图文1🔽', '', '', '', b'\x80\x03]q\x00]q\x01a.', '')
        fqdtw_list = sftw.find_one({'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'})
    
    state = fqdtw_list['state']
    
    # 菜单按钮
    keyboard = [
        [InlineKeyboardButton('🖼 图文设置', callback_data='agent_tuwen'),
         InlineKeyboardButton('🔘 按钮设置', callback_data='agent_anniu')],
        [InlineKeyboardButton('👁 查看图文', callback_data='agent_cattu'),
         InlineKeyboardButton('🚀 立即群发', callback_data='agent_fbgg')],
        [InlineKeyboardButton('🔙 返回管理面板', callback_data='admin_panel')]
    ]
    
    # 状态提示文本
    if state == 1:
        status_text = '📢 <b>用户私信管理</b>\n\n📴 私发状态：<b>已关闭🔴</b>'
    else:
        status_text = '📢 <b>用户私信管理</b>\n\n🟢 私发状态：<b>进行中🟢</b>'
    
    # 发送消息
    query.edit_message_text(
        text=status_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def agent_tuwen(update: Update, context: CallbackContext):
    """设置图文内容"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    context.user_data[f'agent_key{user_id}'] = query.message
    message_id = context.bot.send_message(
        chat_id=user_id, 
        text='请回复图文内容或图片+文字\n\n支持HTML格式',
        reply_markup=ForceReply(force_reply=True)
    )
    context.user_data[f'agent_wanfapeizhi{user_id}'] = message_id
    context.user_data[f'agent_waiting_tuwen{user_id}'] = True


def agent_anniu(update: Update, context: CallbackContext):
    """设置按钮"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    context.user_data[f'agent_key{user_id}'] = query.message
    message_id = context.bot.send_message(
        chat_id=user_id,
        text='请回复按钮设置\n\n格式：按钮名称&链接\n每行一个按钮，多个按钮用 | 分隔\n\n示例：\n官网&https://example.com\n支持&https://t.me/support|购买&https://example.com/buy',
        reply_markup=ForceReply(force_reply=True)
    )
    context.user_data[f'agent_wanfapeizhi{user_id}'] = message_id
    context.user_data[f'agent_waiting_anniu{user_id}'] = True


def agent_cattu(update: Update, context: CallbackContext):
    """预览图文"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    fqdtw_list = sftw.find_one({'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'})
    file_id = fqdtw_list['file_id']
    file_text = fqdtw_list['text']
    file_type = fqdtw_list['send_type']
    key_text = fqdtw_list['key_text']
    keyboard = pickle.loads(fqdtw_list['keyboard'])
    # Preview uses the configured buttons without adding close button
    
    if fqdtw_list['text'] == '' and fqdtw_list['file_id'] == '':
        message_id = context.bot.send_message(chat_id=user_id, text='⚠️ 请先设置图文内容')
        time.sleep(3)
        try:
            context.bot.delete_message(chat_id=user_id, message_id=message_id.message_id)
        except:
            pass
    else:
        # Note: key_text is just stored for reference, not sent to users
        
        if file_type == 'text':
            try:
                message_id = context.bot.send_message(
                    chat_id=user_id, 
                    text=file_text,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                message_id = context.bot.send_message(chat_id=user_id, text=file_text)
        else:
            if file_type == 'photo':
                try:
                    message_id = context.bot.send_photo(
                        chat_id=user_id, 
                        caption=file_text, 
                        photo=file_id,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except:
                    message_id = context.bot.send_photo(chat_id=user_id, caption=file_text, photo=file_id)
            else:
                try:
                    message_id = context.bot.send_animation(
                        chat_id=user_id, 
                        caption=file_text, 
                        animation=file_id,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except:
                    message_id = context.bot.send_animation(chat_id=user_id, caption=file_text, animation=file_id)
        
        time.sleep(3)
        try:
            context.bot.delete_message(chat_id=user_id, message_id=message_id.message_id)
        except:
            pass


def agent_kaiqisifa(update: Update, context: CallbackContext):
    """切换私发状态"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    fqdtw_list = sftw.find_one({'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'})
    current_state = fqdtw_list['state']
    
    # 切换状态：0=开启，1=关闭
    new_state = 0 if current_state == 1 else 1
    sftw.update_one(
        {'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'}, 
        {'$set': {'state': new_state}}
    )
    
    # 更新菜单
    keyboard = [
        [InlineKeyboardButton('🖼 图文设置', callback_data='agent_tuwen'),
         InlineKeyboardButton('🔘 按钮设置', callback_data='agent_anniu')],
        [InlineKeyboardButton('👁 查看图文', callback_data='agent_cattu'),
         InlineKeyboardButton('📢 私发状态', callback_data='agent_kaiqisifa')],
        [InlineKeyboardButton('🚀 立即群发', callback_data='agent_fbgg')],
        [InlineKeyboardButton('🔙 返回管理面板', callback_data='admin_panel')]
    ]
    
    if new_state == 1:
        status_text = '📢 <b>用户私信管理</b>\n\n📴 私发状态：<b>已关闭🔴</b>'
    else:
        status_text = '📢 <b>用户私信管理</b>\n\n🟢 私发状态：<b>已开启🟢</b>'
    
    query.edit_message_text(
        text=status_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def agent_fbgg(update: Update, context: CallbackContext):
    """立即群发广告"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        query.answer("❌ 无权限访问", show_alert=True)
        return
    
    # 获取广告配置
    fqdtw_list = sftw.find_one({'bot_id': AGENT_BOT_ID, 'projectname': '图文1🔽'})
    if not fqdtw_list or (fqdtw_list['text'] == '' and fqdtw_list['file_id'] == ''):
        query.answer("⚠️ 请先设置广告内容", show_alert=True)
        return
    
    file_id = fqdtw_list['file_id']
    file_text = fqdtw_list['text']
    file_type = fqdtw_list['send_type']
    key_text = fqdtw_list['key_text']
    keyboard_data = fqdtw_list['keyboard']
    keyboard = pickle.loads(keyboard_data)
    # Broadcast uses the configured buttons without adding close button
    markup = InlineKeyboardMarkup(keyboard)
    
    # 获取所有用户
    agent_users = get_agent_bot_user_collection(AGENT_BOT_ID)
    user_list = list(agent_users.find({}))
    total_users = len(user_list)
    
    if total_users == 0:
        query.answer("⚠️ 当前没有用户", show_alert=True)
        return
    
    success = 0
    fail = 0
    
    # 初始化进度消息
    progress_msg = context.bot.send_message(
        chat_id=user_id,
        text=f"⏳ 正在准备群发内容，请稍等...\n📤 进度：0/{total_users}",
        parse_mode='HTML'
    )
    
    # 遍历发送
    for idx, u in enumerate(user_list):
        try:
            uid = u['user_id']
            
            # Note: key_text is just stored for reference, not sent to users during broadcast
            
            # 发送主内容
            if file_type == 'text':
                context.bot.send_message(chat_id=uid, text=file_text, parse_mode='HTML', reply_markup=markup)
            elif file_type == 'photo':
                context.bot.send_photo(chat_id=uid, photo=file_id, caption=file_text, parse_mode='HTML', reply_markup=markup)
            elif file_type == 'animation':
                context.bot.send_animation(chat_id=uid, animation=file_id, caption=file_text, parse_mode='HTML', reply_markup=markup)
            else:
                raise Exception("❌ 不支持的发送类型")
            
            success += 1
            time.sleep(BROADCAST_DELAY)  # 防止限流
        except Exception as e:
            fail += 1
            logging.warning(f"发送广告到用户 {uid} 失败: {e}")
        
        # 每10个更新一次进度，或最后一个
        sent = success + fail
        if sent % 10 == 0 or sent == total_users:
            try:
                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=progress_msg.message_id,
                    text=f"📤 私发中：<b>{sent}/{total_users}</b>\n✅ 成功：{success}  ❌ 失败：{fail}",
                    parse_mode='HTML'
                )
            except:
                pass
    
    # 计算成功率
    success_rate = (success / total_users * 100) if total_users > 0 else 0
    
    # 最终结果
    keyboard = [
        [InlineKeyboardButton('🖼 图文设置', callback_data='agent_tuwen'),
         InlineKeyboardButton('🔘 按钮设置', callback_data='agent_anniu')],
        [InlineKeyboardButton('👁 查看图文', callback_data='agent_cattu'),
         InlineKeyboardButton('🚀 立即群发', callback_data='agent_fbgg')],
        [InlineKeyboardButton('🔙 返回管理面板', callback_data='admin_panel')]
    ]
    
    context.bot.edit_message_text(
        chat_id=user_id,
        message_id=progress_msg.message_id,
        text=f"✅ 群发任务已完成！\n\n<b>总用户数：</b>{total_users} 人\n<b>成功：</b>{success} 人\n<b>失败：</b>{fail} 人\n<b>成功率：</b>{success_rate:.1f}%",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def close_message(update: Update, context: CallbackContext):
    """关闭/删除消息"""
    query = update.callback_query
    query.answer()
    
    # 从callback_data提取用户ID或特殊标识
    data = query.data.replace("close_", "")
    user_id = query.from_user.id
    
    # 验证是否是消息的拥有者，或者是广播消息（任何人都可以删除）
    try:
        if str(user_id) == data or data == str(user_id) or data == "broadcast_msg":
            query.delete_message()
        else:
            query.answer("只能删除自己的消息", show_alert=True)
    except Exception as e:
        logging.warning(f"删除消息时出错: {e}")
        try:
            query.delete_message()
        except Exception as e2:
            logging.warning(f"强制删除消息也失败: {e2}")


def main():
    """主函数"""
    # 初始化代理Bot
    init_agent_bot()
    
    # 使用环境变量中的Token
    bot_token = AGENT_BOT_TOKEN
    
    # 初始化支付系统（如果可用）
    if PAYMENT_SYSTEM_AVAILABLE:
        try:
            payment_system = get_payment_system()
            payment_system.start()
            logging.info("✅ 支付系统已启动")
        except Exception as e:
            logging.error(f"❌ 支付系统启动失败: {e}")
    else:
        logging.warning("⚠️ 支付系统不可用，将使用人工充值模式")
    
    # 创建Updater
    updater = Updater(token=bot_token, use_context=True)
    dispatcher = updater.dispatcher
    
    # 注册命令处理器
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('admin', admin_command))
    
    # 注册消息处理器（用于处理购买数量输入和提现地址输入）
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_quantity_input))
    
    # 注册回调处理器 - 商品相关
    dispatcher.add_handler(CallbackQueryHandler(show_product_list, pattern='^product_list$'))
    dispatcher.add_handler(CallbackQueryHandler(show_category_products, pattern=r'^category_'))
    dispatcher.add_handler(CallbackQueryHandler(show_product_detail, pattern=r'^product_'))
    dispatcher.add_handler(CallbackQueryHandler(buy_product, pattern=r'^buy_'))
    dispatcher.add_handler(CallbackQueryHandler(show_usage_instruction, pattern=r'^usage_'))
    dispatcher.add_handler(CallbackQueryHandler(confirm_buy_product, pattern=r'^confirm_buy_'))
    
    # 用户中心相关
    #dispatcher.add_handler(CallbackQueryHandler(show_user_center, pattern='^user_center$'))
    #dispatcher.add_handler(CallbackQueryHandler(show_my_orders, pattern='^my_orders$'))
    dispatcher.add_handler(CallbackQueryHandler(show_recharge, pattern='^recharge$'))
    dispatcher.add_handler(CallbackQueryHandler(show_contact_support, pattern='^contact_support$'))
    dispatcher.add_handler(CallbackQueryHandler(show_purchase_notice, pattern='^purchase_notice$'))
    dispatcher.add_handler(CallbackQueryHandler(show_purchase_history, pattern='^purchase_history$'))
    dispatcher.add_handler(CallbackQueryHandler(download_order, pattern=r'^download_order_'))
    dispatcher.add_handler(CallbackQueryHandler(show_order_detail, pattern=r'^order_detail_'))    
    # 充值相关（新增）
    dispatcher.add_handler(CallbackQueryHandler(handle_recharge_amount, pattern=r'^recharge_amount_'))
    dispatcher.add_handler(CallbackQueryHandler(handle_recharge_custom, pattern='^recharge_custom$'))
    dispatcher.add_handler(CallbackQueryHandler(cancel_recharge_order, pattern=r'^cancel_order_'))
    
    # 国家/区号搜索相关
    dispatcher.add_handler(CallbackQueryHandler(show_country_search, pattern='^country_search$'))
    
    #切换语言相关
    dispatcher.add_handler(CallbackQueryHandler(show_switch_lang, pattern='^switch_lang$'))
    dispatcher.add_handler(CallbackQueryHandler(set_user_lang, pattern=r'^set_lang_'))
    
    # 管理面板相关
    dispatcher.add_handler(CallbackQueryHandler(lambda u, c: show_admin_panel(u, c, False), pattern='^admin_panel$'))
    
    # 用户列表相关
    dispatcher.add_handler(CallbackQueryHandler(show_admin_users, pattern='^admin_users$'))
    dispatcher.add_handler(CallbackQueryHandler(show_admin_users_list, pattern=r'^admin_users_filter_'))
    
    # 销售统计相关
    dispatcher.add_handler(CallbackQueryHandler(show_admin_stats, pattern='^admin_stats$'))
    dispatcher.add_handler(CallbackQueryHandler(show_admin_stats_detail, pattern=r'^admin_stats_(today|yesterday|week|month|all)$'))
    
    # 提现相关
    dispatcher.add_handler(CallbackQueryHandler(show_admin_withdraw, pattern='^admin_withdraw$'))
    dispatcher.add_handler(CallbackQueryHandler(show_admin_withdraw_apply, pattern='^admin_withdraw_apply$'))
    dispatcher.add_handler(CallbackQueryHandler(handle_withdraw_amount, pattern=r'^admin_withdraw_amount_'))
    dispatcher.add_handler(CallbackQueryHandler(bind_wallet_address, pattern=r'^admin_withdraw_bind_address$'))
    dispatcher.add_handler(CallbackQueryHandler(submit_withdraw, pattern=r'^admin_withdraw_confirm$'))
    dispatcher.add_handler(CallbackQueryHandler(submit_withdraw, pattern=r'^admin_withdraw_confirm_final$'))
    dispatcher.add_handler(CallbackQueryHandler(show_withdraw_records, pattern=r'^admin_withdraw_records_'))
    
    # 商品库存相关
    dispatcher.add_handler(CallbackQueryHandler(show_admin_inventory, pattern='^admin_inventory$'))
    dispatcher.add_handler(CallbackQueryHandler(show_admin_inventory_list, pattern=r'^admin_inventory_filter_'))
    
    # 用户私信相关
    dispatcher.add_handler(CallbackQueryHandler(agent_sifa, pattern='^agent_sifa$'))
    dispatcher.add_handler(CallbackQueryHandler(agent_tuwen, pattern='^agent_tuwen$'))
    dispatcher.add_handler(CallbackQueryHandler(agent_anniu, pattern='^agent_anniu$'))
    dispatcher.add_handler(CallbackQueryHandler(agent_cattu, pattern='^agent_cattu$'))
    dispatcher.add_handler(CallbackQueryHandler(agent_kaiqisifa, pattern='^agent_kaiqisifa$'))
    dispatcher.add_handler(CallbackQueryHandler(agent_fbgg, pattern='^agent_fbgg$'))
    
    # 其他
    dispatcher.add_handler(CallbackQueryHandler(back_to_main, pattern='^back_to_main$'))
    dispatcher.add_handler(CallbackQueryHandler(close_message, pattern=r'^close_'))
    
    # 启动Bot
    logging.info(f"🚀 代理Bot启动: {AGENT_INFO.get('agent_name')} (@{AGENT_INFO.get('agent_username')})")
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()


# ==================== 配置管理模块 ====================

import logging
from mongo import agent_bots


def validate_agent_config(agent_bot_id: str) -> tuple:
    """
    验证代理配置是否完整
    
    Returns:
        (is_valid, error_message)
    """
    # 检查代理是否存在
    agent = agent_bots.find_one({'agent_bot_id': agent_bot_id})
    
    if not agent:
        return False, f"代理不存在: {agent_bot_id}"
    
    # 检查状态
    if agent.get('status') != 'active':
        return False, f"代理已停用: {agent.get('status')}"
    
    # 检查Bot Token
    if not agent.get('agent_token'):
        return False, "缺少 Bot Token"
    
    # 检查佣金比例
    commission_rate = agent.get('commission_rate', 0)
    if commission_rate <= 0 or commission_rate > 100:
        return False, f"佣金比例异常: {commission_rate}%"
    
    return True, "配置验证通过"


def get_agent_config(agent_bot_id: str) -> dict:
    """
    获取代理配置信息
    
    Returns:
        代理配置字典
    """
    agent = agent_bots.find_one({'agent_bot_id': agent_bot_id})
    
    if not agent:
        return {}
    
    return {
        'agent_bot_id': agent.get('agent_bot_id'),
        'agent_name': agent.get('agent_name'),
        'agent_token': agent.get('agent_token'),
        'agent_username': agent.get('agent_username'),
        'commission_rate': agent.get('commission_rate', 0),
        'status': agent.get('status'),
        'settings': agent.get('settings', {})
    }


def update_agent_last_sync(agent_bot_id: str):
    """更新代理最后同步时间"""
    from mongo import beijing_now_str
    
    agent_bots.update_one(
        {'agent_bot_id': agent_bot_id},
        {'$set': {'last_sync_time': beijing_now_str()}}
    )
    
    logging.info(f"✅ 更新代理同步时间: {agent_bot_id}")


# ==================== 库存同步模块 ====================

import logging
import time
from datetime import datetime, timedelta
from mongo import (
    agent_bots,
    agent_product_prices,
    ejfl,
    fenlei,
    hb,
    get_real_time_stock,
    beijing_now_str
)


class InventorySync:
    """库存同步管理器"""
    
    def __init__(self, agent_bot_id: str):
        self.agent_bot_id = agent_bot_id
        self.agent_info = agent_bots.find_one({'agent_bot_id': agent_bot_id})
        
        if not self.agent_info:
            raise ValueError(f"代理不存在: {agent_bot_id}")
        
        self.commission_rate = self.agent_info.get('commission_rate', 0) / 100
        logging.info(f"✅ 库存同步器初始化: {self.agent_info.get('agent_name')}")
    
    def sync_all_products(self) -> dict:
        """
        同步所有商品的库存和价格信息
        
        Returns:
            同步结果统计
        """
        logging.info(f"开始同步所有商品: {self.agent_bot_id}")
        
        success_count = 0
        failed_count = 0
        updated_count = 0
        
        try:
            # 获取所有商品
            products = list(ejfl.find({}))
            
            for product in products:
                try:
                    nowuid = product.get('nowuid')
                    product_name = product.get('projectname', '未知商品')
                    hq_price = float(product.get('money', 0))
                    uid = product.get('uid')
                    
                    # 获取分类名称
                    category = fenlei.find_one({'uid': uid})
                    category_name = category.get('projectname', '未知分类') if category else '未知分类'
                    
                    # 计算代理价格
                    agent_price = hq_price * (1 + self.commission_rate)
                    
                    # 获取库存
                    stock = get_real_time_stock(nowuid)
                    
                    # 检查是否已存在价格记录
                    existing = agent_product_prices.find_one({
                        'agent_bot_id': self.agent_bot_id,
                        'original_nowuid': nowuid
                    })
                    
                    if existing:
                        # 更新现有记录
                        result = agent_product_prices.update_one(
                            {
                                'agent_bot_id': self.agent_bot_id,
                                'original_nowuid': nowuid
                            },
                            {
                                '$set': {
                                    'product_name': product_name,
                                    'category': category_name,
                                    'original_price': hq_price,
                                    'agent_price': agent_price,
                                    'commission_rate': self.commission_rate * 100,
                                    'current_stock': stock,
                                    'last_sync_time': beijing_now_str()
                                }
                            }
                        )
                        if result.modified_count > 0:
                            updated_count += 1
                    else:
                        # 创建新记录
                        agent_product_prices.insert_one({
                            'agent_bot_id': self.agent_bot_id,
                            'original_nowuid': nowuid,
                            'product_name': product_name,
                            'category': category_name,
                            'original_price': hq_price,
                            'agent_price': agent_price,
                            'commission_rate': self.commission_rate * 100,
                            'is_active': True,
                            'current_stock': stock,
                            'sales_count': 0,
                            'total_revenue': 0.0,
                            'last_sale_time': '',
                            'creation_time': beijing_now_str(),
                            'last_sync_time': beijing_now_str()
                        })
                        success_count += 1
                    
                except Exception as e:
                    logging.error(f"同步商品失败 {nowuid}: {e}")
                    failed_count += 1
            
            # 更新代理最后同步时间
            agent_bots.update_one(
                {'agent_bot_id': self.agent_bot_id},
                {'$set': {'last_sync_time': beijing_now_str()}}
            )
            
            result = {
                'success_count': success_count,
                'updated_count': updated_count,
                'failed_count': failed_count,
                'total_products': len(products)
            }
            
            logging.info(f"✅ 商品同步完成: {result}")
            return result
            
        except Exception as e:
            logging.error(f"❌ 同步失败: {e}")
            return {
                'success_count': 0,
                'updated_count': 0,
                'failed_count': 0,
                'total_products': 0,
                'error': str(e)
            }
    
    def sync_single_product(self, nowuid: str) -> bool:
        """
        同步单个商品的库存和价格
        
        Args:
            nowuid: 商品ID
            
        Returns:
            是否同步成功
        """
        try:
            # 获取商品信息
            product = ejfl.find_one({'nowuid': nowuid})
            if not product:
                logging.warning(f"商品不存在: {nowuid}")
                return False
            
            product_name = product.get('projectname', '未知商品')
            hq_price = float(product.get('money', 0))
            uid = product.get('uid')
            
            # 获取分类
            category = fenlei.find_one({'uid': uid})
            category_name = category.get('projectname', '未知分类') if category else '未知分类'
            
            # 计算价格
            agent_price = hq_price * (1 + self.commission_rate)
            
            # 获取库存
            stock = get_real_time_stock(nowuid)
            
            # 更新或创建记录
            agent_product_prices.update_one(
                {
                    'agent_bot_id': self.agent_bot_id,
                    'original_nowuid': nowuid
                },
                {
                    '$set': {
                        'product_name': product_name,
                        'category': category_name,
                        'original_price': hq_price,
                        'agent_price': agent_price,
                        'current_stock': stock,
                        'last_sync_time': beijing_now_str()
                    },
                    '$setOnInsert': {
                        'commission_rate': self.commission_rate * 100,
                        'is_active': True,
                        'sales_count': 0,
                        'total_revenue': 0.0,
                        'creation_time': beijing_now_str()
                    }
                },
                upsert=True
            )
            
            logging.info(f"✅ 同步商品: {product_name} (nowuid={nowuid})")
            return True
            
        except Exception as e:
            logging.error(f"❌ 同步商品失败 {nowuid}: {e}")
            return False
    
    def check_low_stock(self, threshold: int = 10) -> list:
        """
        检查低库存商品
        
        Args:
            threshold: 库存阈值
            
        Returns:
            低库存商品列表
        """
        low_stock_products = []
        
        try:
            # 获取所有商品
            products = list(ejfl.find({}))
            
            for product in products:
                nowuid = product.get('nowuid')
                product_name = product.get('projectname', '未知商品')
                stock = get_real_time_stock(nowuid)
                
                if 0 < stock <= threshold:
                    low_stock_products.append({
                        'nowuid': nowuid,
                        'product_name': product_name,
                        'stock': stock
                    })
            
            if low_stock_products:
                logging.warning(f"⚠️ 发现 {len(low_stock_products)} 个低库存商品")
            
            return low_stock_products
            
        except Exception as e:
            logging.error(f"❌ 检查低库存失败: {e}")
            return []
    
    def check_out_of_stock(self) -> list:
        """
        检查缺货商品
        
        Returns:
            缺货商品列表
        """
        out_of_stock_products = []
        
        try:
            # 获取所有商品
            products = list(ejfl.find({}))
            
            for product in products:
                nowuid = product.get('nowuid')
                product_name = product.get('projectname', '未知商品')
                stock = get_real_time_stock(nowuid)
                
                if stock == 0:
                    out_of_stock_products.append({
                        'nowuid': nowuid,
                        'product_name': product_name
                    })
            
            if out_of_stock_products:
                logging.warning(f"⚠️ 发现 {len(out_of_stock_products)} 个缺货商品")
            
            return out_of_stock_products
            
        except Exception as e:
            logging.error(f"❌ 检查缺货失败: {e}")
            return []


class PriceValidator:
    """价格验证器"""
    
    @staticmethod
    def validate_agent_price(hq_price: float, agent_price: float, commission_rate: float) -> tuple:
        """
        验证代理价格是否合理
        
        Args:
            hq_price: 总部价格
            agent_price: 代理价格
            commission_rate: 佣金比例（小数形式，如0.25表示25%）
            
        Returns:
            (is_valid, error_message)
        """
        # 计算最低允许价格
        min_agent_price = hq_price * (1 + commission_rate)
        
        if agent_price < hq_price:
            return False, f"代理价格不能低于总部价格（{hq_price:.2f} USDT）"
        
        if agent_price < min_agent_price:
            return False, f"代理价格过低，最低应为 {min_agent_price:.2f} USDT（含{commission_rate*100:.0f}%佣金）"
        
        # 价格过高警告（超过100%加价）
        if agent_price > hq_price * 2:
            return True, f"警告：价格过高（超过总部价格100%），可能影响销售"
        
        return True, "价格验证通过"
    
    @staticmethod
    def calculate_profit(hq_price: float, agent_price: float) -> float:
        """
        计算利润
        
        Args:
            hq_price: 总部价格
            agent_price: 代理价格
            
        Returns:
            利润金额
        """
        return max(0, agent_price - hq_price)
    
    @staticmethod
    def calculate_commission(hq_price: float, commission_rate: float) -> float:
        """
        计算佣金
        
        Args:
            hq_price: 总部价格
            commission_rate: 佣金比例（小数形式）
            
        Returns:
            佣金金额
        """
        return hq_price * commission_rate


def sync_products_for_all_agents():
    """为所有活跃代理同步商品"""
    logging.info("开始为所有代理同步商品")
    
    active_agents = list(agent_bots.find({'status': 'active'}))
    
    results = []
    for agent in active_agents:
        agent_bot_id = agent.get('agent_bot_id')
        agent_name = agent.get('agent_name', '未知代理')
        
        try:
            sync = InventorySync(agent_bot_id)
            result = sync.sync_all_products()
            results.append({
                'agent_name': agent_name,
                'result': result
            })
            logging.info(f"✅ {agent_name} 同步完成: {result}")
        except Exception as e:
            logging.error(f"❌ {agent_name} 同步失败: {e}")
            results.append({
                'agent_name': agent_name,
                'result': {'error': str(e)}
            })
    
    logging.info(f"所有代理同步完成，共 {len(results)} 个代理")
    return results


def periodic_sync_task(interval_minutes: int = 30):
    """
    定期同步任务
    
    Args:
        interval_minutes: 同步间隔（分钟）
    """
    logging.info(f"启动定期同步任务，间隔 {interval_minutes} 分钟")
    
    while True:
        try:
            logging.info("执行定期同步...")
            results = sync_products_for_all_agents()
            
            # 统计结果
            total_success = sum(r['result'].get('success_count', 0) for r in results)
            total_updated = sum(r['result'].get('updated_count', 0) for r in results)
            total_failed = sum(r['result'].get('failed_count', 0) for r in results)
            
            logging.info(f"定期同步完成: 新增={total_success}, 更新={total_updated}, 失败={total_failed}")
            
        except Exception as e:
            logging.error(f"定期同步失败: {e}")
        
        # 等待下次同步
        time.sleep(interval_minutes * 60)


if __name__ == '__main__':
    # 测试同步功能
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python3 agent/inventory_sync.py <agent_bot_id>")
        sys.exit(1)
    
    agent_bot_id = sys.argv[1]
    
    # 创建同步器
    sync = InventorySync(agent_bot_id)
    
    # 执行同步
    result = sync.sync_all_products()
    print(f"同步结果: {result}")
    
    # 检查低库存
    low_stock = sync.check_low_stock()
    if low_stock:
        print(f"\n低库存商品 ({len(low_stock)}个):")
        for item in low_stock[:5]:
            print(f"  - {item['product_name']}: {item['stock']} 件")
    
    # 检查缺货
    out_of_stock = sync.check_out_of_stock()
    if out_of_stock:
        print(f"\n缺货商品 ({len(out_of_stock)}个):")
        for item in out_of_stock[:5]:
            print(f"  - {item['product_name']}")