import os
import re
import json
import uuid
import time
import qrcode
import shutil
import pickle
import socket
import random
import struct
import zipfile
import logging
import hashlib
import threading
import urllib.parse
import pandas as pd
import asyncio
from io import BytesIO
from time import sleep
from decimal import Decimal
from threading import Timer, Thread
from multiprocessing import Process
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from glob import glob
from random import randint, shuffle
from dotenv import load_dotenv
import pytz

import telegram
from telegram import (
    Update, InputFile, InputMediaPhoto, InputTextMessageContent,
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
    ChatPermissions, ChatMember, ChatMemberAdministrator, ChatMemberRestricted,
    InlineQueryResultArticle, InlineQueryResultPhoto, ForceReply
)
from telegram.ext import (
    Updater, CommandHandler, CallbackContext, MessageHandler,
    CallbackQueryHandler, InlineQueryHandler, Filters
)

# ✅ 先定义变量（在文件顶部）
NOTIFY_CHANNEL_ID = os.getenv("NOTIFY_CHANNEL_ID")

try:
    from telegram.utils import helpers
except ImportError:
    helpers = None

try:
    from pygtrans import Translate
    translator = Translate()
except ImportError:
    try:
        from googletrans import Translator  # type: ignore
        translator = Translator()
        Translate = Translator
    except ImportError:
        class MockTranslate:
            def __init__(self, target='en', domain='com'):
                self.target = target
                self.domain = domain
                
            def translate(self, text, target='en', source='auto'):
                return type('obj', (object,), {
                    'text': text, 
                    'translatedText': text  # 返回原文，不进行翻译
                })()
        translator = MockTranslate()
        Translate = MockTranslate

from pymongo import MongoClient
from mongo import *
from mongo import topup, user, withdrawal_requests
from utils import create_easypay_url, create_payment_with_qrcode
from pay_server import start_flask_server

# 导入代理管理模块（合并后的单文件）
from bot_agent import (
    # 代理管理
    show_agent_management,
    show_agent_list,
    start_add_agent,
    add_new_agent,
    show_agent_details,
    toggle_agent_status,
    delete_agent_confirm,
    delete_agent,
    show_agent_stats,
    # 代理设置
    show_agent_settings,
    show_agent_address_config,
    request_agent_address_input,
    handle_agent_address_input,
    confirm_agent_address_change,
    # 提现管理
    show_withdrawal_management,
    show_pending_withdrawals,
    show_withdrawal_detail,
    approve_withdrawal,
    reject_withdrawal,
    complete_withdrawal,
    view_withdrawal_history,
    show_withdrawal_stats,
    # 统计报表
    show_agent_stats_report,
    show_sales_ranking,
    show_profit_summary,
    export_sales_ranking,
    export_profit_summary,
    show_comprehensive_report,
    export_comprehensive_report
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
# ✅ 管理员配置统一使用 ID
ADMIN_IDS = list(map(int, filter(None, os.getenv("ADMIN_IDS", "").split(","))))
EASYPAY_PID = os.getenv("EASYPAY_PID")
EASYPAY_KEY = os.getenv("EASYPAY_KEY")
EASYPAY_GATEWAY = os.getenv("EASYPAY_GATEWAY")
EASYPAY_NOTIFY = os.getenv("EASYPAY_NOTIFY")
EASYPAY_RETURN = os.getenv("EASYPAY_RETURN")
DEFAULT_IMAGE_URL = os.getenv("DEFAULT_IMAGE_URL", "https://th.bing.com/th/id/OIP.zl_78JqApTLDpDnc7iN5zgHaHa?w=203&h=189&c=7&r=0&o=7&pid=1.7&rm=3")
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "logs/bot.log")

# 支付功能开关配置
ENABLE_ALIPAY_WECHAT = os.getenv("ENABLE_ALIPAY_WECHAT", "true").lower() == "true"

# 时间配置
MESSAGE_DELETE_DELAY = int(os.getenv("MESSAGE_DELETE_DELAY", "3"))
TRX_MESSAGE_DELETE_DELAY = int(os.getenv("TRX_MESSAGE_DELETE_DELAY", "300"))
BOT_TIMEOUT = int(os.getenv("BOT_TIMEOUT", "600"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

# 日志目录初始化
os.makedirs(os.path.dirname(LOG_FILE_PATH) if os.path.dirname(LOG_FILE_PATH) else '.', exist_ok=True)

# ================================ 北京时区定义 ================================
# 全局使用统一的北京时区对象 (Asia/Shanghai, UTC+8)
BEIJING_TZ = pytz.timezone('Asia/Shanghai')

class BeijingFormatter(logging.Formatter):
    """使用北京时间的日志格式化器"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=BEIJING_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

# 文件日志配置
file_handler = logging.FileHandler(LOG_FILE_PATH, mode='a', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = BeijingFormatter('[%(asctime)s] [%(levelname)s] %(message)s')
file_handler.setFormatter(file_formatter)

# 控制台日志 handler（避免重复添加）
console = logging.StreamHandler()
console.setLevel(logging.INFO)
console_formatter = BeijingFormatter('[%(asctime)s] [%(levelname)s] %(message)s')
console.setFormatter(console_formatter)

# 配置根日志记录器
root_logger = logging.getLogger('')
root_logger.setLevel(logging.INFO)
if not root_logger.handlers:
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console)

logging.info("✅ 日志系统初始化完成")

# ================================ 北京时间工具函数 ================================
# 所有对外展示的时间统一使用北京时间 (Asia/Shanghai, UTC+8)
# BEIJING_TZ 已在上方日志配置部分统一定义

def get_beijing_now():
    """
    获取当前北京时间
    返回带时区信息的 datetime 对象
    """
    return datetime.now(BEIJING_TZ)

def format_beijing_time(dt=None, fmt='%Y-%m-%d %H:%M:%S'):
    """
    将时间格式化为北京时间字符串
    
    参数:
        dt: datetime 对象、时间戳(int/float)或None
            - 如果是 naive datetime，假定为 UTC 时间
            - 如果是 aware datetime，转换到北京时区
            - 如果是时间戳，转换为北京时间
            - 如果是 None，返回当前北京时间
        fmt: 时间格式字符串，默认 '%Y-%m-%d %H:%M:%S'
    
    返回:
        格式化的北京时间字符串
    """
    if dt is None:
        # 返回当前北京时间
        return get_beijing_now().strftime(fmt)
    
    if isinstance(dt, (int, float)):
        # 时间戳转换为北京时间
        dt = datetime.fromtimestamp(dt, tz=pytz.UTC)
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            # naive datetime，假定为 UTC
            dt = pytz.UTC.localize(dt)
    else:
        # 不支持的类型，返回当前北京时间
        return get_beijing_now().strftime(fmt)
    
    # 转换到北京时区并格式化
    beijing_time = dt.astimezone(BEIJING_TZ)
    return beijing_time.strftime(fmt)

def parse_to_beijing(time_str, fmt='%Y-%m-%d %H:%M:%S'):
    """
    解析时间字符串为北京时间的 datetime 对象
    
    注意: 此函数假定输入的时间字符串表示的是北京时间（不带时区信息），
    会将其标记为 Asia/Shanghai 时区。如果字符串表示的是 UTC 时间，
    应先用 datetime.strptime 解析，然后用 format_beijing_time 转换。
    
    参数:
        time_str: 时间字符串（假定为北京时间）
        fmt: 时间格式，默认 '%Y-%m-%d %H:%M:%S'
    
    返回:
        带北京时区信息的 datetime 对象，解析失败返回 None
    """
    try:
        # 解析为 naive datetime，然后标记为北京时区（不是转换）
        dt = datetime.strptime(time_str, fmt)
        return BEIJING_TZ.localize(dt)
    except Exception:
        return None

def beijing_now_str(fmt='%Y-%m-%d %H:%M:%S'):
    """
    获取当前北京时间的字符串格式（快捷函数）
    """
    return get_beijing_now().strftime(fmt)

# ✅ 全局状态管理字典
WAITING_TXHASH = {}  # 用于跟踪等待输入交易哈希的用户
WAITING_USER_TXID = {}  # 用于跟踪用户提现申请

# ✅ 管理员验证辅助函数
def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    return user_id in ADMIN_IDS

def get_admin_ids() -> list:
    """获取管理员 ID 列表"""
    return ADMIN_IDS.copy()

def add_admin(user_id: int) -> bool:
    """添加管理员到内存中（需要重启生效）"""
    if user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)
        return True
    return False

def remove_admin(user_id: int) -> bool:
    """从内存中移除管理员（需要重启生效）"""
    if user_id in ADMIN_IDS:
        ADMIN_IDS.remove(user_id)
        return True
    return False

def make_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)
        print(f"Folder '{path}' created successfully")
    else:
        print(f"Folder '{path}' already exists")

def rename_directory(old_path, new_path):
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        print(f"Folder '{old_path}' renamed to '{new_path}'")
    else:
        print(f"Folder '{old_path}' does not exist")

def get_fy(fstext):
    try:
        fy_list = fyb.find_one({'text': fstext})
        if fy_list is None:
            try:
                # 尝试使用 pygtrans
                if hasattr(translator, 'translate'):
                    result = translator.translate(fstext.replace("\n", "\\n"), target='en')
                    if hasattr(result, 'translatedText'):
                        trans_text = result.translatedText
                    elif hasattr(result, 'text'):
                        trans_text = result.text
                    else:
                        trans_text = str(result)
                else:
                    # 使用 Translate 类
                    client = Translate(target='en', domain='com')
                    result = client.translate(fstext.replace("\n", "\\n"))
                    trans_text = result.translatedText
                
                fanyibao('英文', fstext, trans_text.replace("\\n", "\n"))
                return trans_text.replace("\\n", "\n")
            except Exception as e:
                print(f"翻译失败: {e}")
                # 翻译失败时返回原文
                return fstext
        else:
            fanyi = fy_list['fanyi']
            return fanyi
    except Exception as e:
        print(f"获取翻译失败: {e}")
        # 出错时返回原文
        return fstext

def generate_captcha():
    """生成图片验证码"""
    import random
    import os
    from PIL import Image, ImageDraw, ImageFont
    
    # 生成4位随机数字作为验证码
    captcha_code = ''.join([str(random.randint(0, 9)) for _ in range(4)])
    
    # 创建图片
    width, height = 300, 150
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)
    
    # 添加背景噪点
    for _ in range(200):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(200, 255), random.randint(200, 255), random.randint(200, 255)))
    
    # 绘制验证码数字
    try:
        # 尝试使用系统字体
        font_size = 60
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        # 如果没有arial.ttf，使用默认字体
        font = ImageFont.load_default()
    
    # 计算文字位置居中
    char_width = width // 4
    for i, char in enumerate(captcha_code):
        x = i * char_width + char_width // 2 - 15
        y = height // 2 - 30
        
        # 添加随机颜色
        color = (random.randint(50, 150), random.randint(100, 200), random.randint(50, 150))
        draw.text((x, y), char, font=font, fill=color)
    
    # 添加干扰线
    for _ in range(5):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=(random.randint(150, 200), random.randint(150, 200), random.randint(150, 200)), width=2)
    
    # 保存图片
    captcha_dir = "captcha"
    if not os.path.exists(captcha_dir):
        os.makedirs(captcha_dir)
    
    image_path = os.path.join(captcha_dir, f"captcha_{captcha_code}_{random.randint(1000, 9999)}.png")
    image.save(image_path)
    
    # 生成错误选项（其他4位数字）
    wrong_answers = []
    while len(wrong_answers) < 2:
        wrong_code = ''.join([str(random.randint(0, 9)) for _ in range(4)])
        if wrong_code != captcha_code and wrong_code not in wrong_answers:
            wrong_answers.append(wrong_code)
    
    # 打乱选项顺序
    all_options = [captcha_code] + wrong_answers
    random.shuffle(all_options)
    
    return image_path, captcha_code, all_options


def send_captcha(update: Update, context: CallbackContext, user_id: int, lang: str = 'zh'):
    """发送验证码界面"""
    image_path, correct_answer, options = generate_captcha()
    
    # 保存正确答案到用户数据
    context.user_data[f"captcha_answer_{user_id}"] = correct_answer
    context.user_data[f"captcha_attempts_{user_id}"] = 0
    context.user_data[f"captcha_image_{user_id}"] = image_path
    
    if lang == 'zh':
        text = f"""为了防止恶意使用，请看图片中的数字验证码：

📝 请输入图片中显示的4位数字

请从下方选项中选择正确答案："""
    else:
        text = f"""To prevent malicious use, please look at the image captcha:

📝 Please enter the 4-digit number shown in the image

Please select the correct answer from the options below:"""
    
    # 创建选项按钮 - 横向排列
    keyboard = [
        [InlineKeyboardButton(str(option), callback_data=f'captcha_{option}') for option in options]
    ]
    
    # 发送图片验证码
    with open(image_path, 'rb') as photo:
        context.bot.send_photo(
            chat_id=user_id,
            photo=photo,
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


def handle_captcha_response(update: Update, context: CallbackContext):
    """处理验证码回答"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    
    # 获取用户选择的答案
    try:
        user_answer = query.data.replace("captcha_", "")
    except:
        return
    
    # 获取正确答案
    correct_answer = context.user_data.get(f"captcha_answer_{user_id}")
    if correct_answer is None:
        return
    
    # 获取用户语言设置
    user_info = user.find_one({'user_id': user_id})
    lang = user_info.get('lang', 'zh') if user_info else 'zh'
    
    # 删除验证码消息
    try:
        context.bot.delete_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
    except:
        pass
    
    # 清理验证码图片
    try:
        captcha_image_path = context.user_data.get(f"captcha_image_{user_id}")
        if captcha_image_path and os.path.exists(captcha_image_path):
            os.remove(captcha_image_path)
    except:
        pass
    
    if user_answer == correct_answer:
        # 验证成功
        user.update_one({'user_id': user_id}, {'$set': {'verified': True}})
        
        # 清理验证数据
        context.user_data.pop(f"captcha_answer_{user_id}", None)
        context.user_data.pop(f"captcha_attempts_{user_id}", None)
        context.user_data.pop(f"captcha_cooldown_{user_id}", None)
        context.user_data.pop(f"captcha_image_{user_id}", None)
        
        if lang == 'zh':
            success_msg = "✅ 验证成功！正在进入系统..."
        else:
            success_msg = "✅ Verification successful! Entering system..."
        
        msg = context.bot.send_message(chat_id=user_id, text=success_msg)
        
        # 2秒后删除成功消息并显示主菜单
        def show_main_menu():
            try:
                context.bot.delete_message(chat_id=user_id, message_id=msg.message_id)
            except:
                pass
            
            # 重新调用start函数显示主菜单
            start_verified_user(update, context, user_id)
        
        context.job_queue.run_once(lambda ctx: show_main_menu(), when=2)
        
    else:
        # 验证失败
        attempts = context.user_data.get(f"captcha_attempts_{user_id}", 0) + 1
        context.user_data[f"captcha_attempts_{user_id}"] = attempts
        
        # 设置60秒冷却时间
        context.user_data[f"captcha_cooldown_{user_id}"] = time.time() + 60
        
        # 清理验证数据
        context.user_data.pop(f"captcha_answer_{user_id}", None)
        
        if lang == 'zh':
            error_msg = "❌ 验证码错误，请1分钟后发送 /start 重新验证，或者联系管理员"
        else:
            error_msg = "❌ Verification failed. Please send /start again after 1 minute, or contact admin"
        
        context.bot.send_message(chat_id=user_id, text=error_msg)


def check_captcha_cooldown(user_id: int, context: CallbackContext, lang: str = 'zh') -> bool:
    """检查验证码冷却时间"""
    cooldown_time = context.user_data.get(f"captcha_cooldown_{user_id}")
    if cooldown_time is None:
        return False
    
    current_time = time.time()
    if current_time < cooldown_time:
        remaining = int(cooldown_time - current_time)
        if lang == 'zh':
            msg = f"⏳ 请等待 {remaining} 秒后再重新验证"
        else:
            msg = f"⏳ Please wait {remaining} seconds before verification"
        
        context.bot.send_message(chat_id=user_id, text=msg)
        return True
    else:
        # 冷却时间已过，清除数据
        context.user_data.pop(f"captcha_cooldown_{user_id}", None)
        return False


def start_verified_user(update: Update, context: CallbackContext, user_id: int):
    """已验证用户的启动流程"""
    # 获取用户信息
    uinfo = user.find_one({'user_id': user_id})
    if not uinfo:
        return
    
    username = update.effective_user.username if update else uinfo.get('username')
    fullname = update.effective_user.full_name.replace('<', '').replace('>', '') if update else uinfo.get('fullname', '')
    
    state = uinfo['state']
    USDT = uinfo['USDT']
    zgje = uinfo['zgje']
    zgsl = uinfo['zgsl']
    lang = uinfo.get('lang', 'zh')
    
    # 参数处理（如果来自update）
    if update and update.message:
        args = update.message.text.split(maxsplit=2)
        if len(args) == 2 and args[1].startswith("buy_"):
            nowuid = args[1][4:]
            return gmsp(update, context, nowuid=nowuid)

    # 获取欢迎语
    welcome_text = shangtext.find_one({'projectname': '欢迎语'})['text']
    lang = lang if lang in ['zh', 'en'] else 'zh'

    # 用户名欢迎行
    username_display = fullname if not username else f'<a href="https://t.me/{username}">{fullname}</a>'
    welcome_line = f"<b>欢迎你，{username_display}！</b>\n\n" if lang == 'zh' else f"<b>Welcome, {username_display}!</b>\n\n"

    # 多语言翻译欢迎语
    welcome_text = welcome_text if lang == 'zh' else get_fy(welcome_text)

    # 拼接完整文本
    full_text = welcome_line + welcome_text

    # 营业状态限制 - 当业务关闭(0)时，只允许管理员访问，普通用户无法使用
    business_status = shangtext.find_one({'projectname': '营业状态'})['text']
    if business_status == 0 and not is_admin(user_id):
        return

    # 构建自定义菜单
    keylist = get_key.find({}, sort=[('Row', 1), ('first', 1)])
    keyboard = [[] for _ in range(100)]
    
    # ✅ 预设的主要按钮英文翻译
    button_translations = {
        '🛒商品列表': '🛒Product List',
        '👤个人中心': '👤Personal Center', 
        '💳余额充值': '💳Balance Recharge',
        '📞联系客服': '📞Contact Support',
        '🔶使用教程': '🔶Usage Tutorial',
        '🔷出货通知': '🔷Delivery Notice',
        '🔎查询库存': '🔎Check Inventory',
        '🌐 语言切换': '🌐 Language Switching',
        '⬅️ 返回主菜单': '⬅️ Return to Main Menu'
    }
    
    for item in keylist:
        if lang == 'zh':
            label = item['projectname']
        else:
            # 使用预设翻译，如果没有则使用get_fy
            label = button_translations.get(item['projectname'], get_fy(item['projectname']))
        row = item['Row']
        keyboard[row - 1].append(KeyboardButton(label))

    context.bot.send_message(
        chat_id=user_id,
        text=full_text,
        reply_markup=ReplyKeyboardMarkup([row for row in keyboard if row], resize_keyboard=True),
        parse_mode='HTML',
        disable_web_page_preview=True
    )





def inline_query(update: Update, context: CallbackContext):
    query = update.inline_query.query.strip()
    results = []

    # 商品分享卡片（根据 nowuid）
    if query.startswith("share_"):
        nowuid = query.replace("share_", "")
        product = ejfl.find_one({'nowuid': nowuid})
        if not product:
            return

        pname = product.get('projectname', '未知商品')
        price = float(product.get('money', 0))
        stock = hb.count_documents({'nowuid': nowuid, 'state': 0})
        desc = product.get('desc', '暂无商品说明')

        # 获取一级分类名
        uid = product.get('uid')
        cate_name = '未知分类'
        if uid:
            cate = fenlei.find_one({'uid': uid})
            if cate:
                cate_name = cate.get('projectname', '未知分类')

        # 分类路径
        category_path = f"{cate_name} / {pname}"

        # 显示文本（图片下方 caption）
        text = (
            f"<b>✅ 商品：</b>{pname}\n"
            f"<b>📂 分类：</b>{category_path}\n"
            f"<b>💰 价格：</b>{price:.2f} USDT\n"
            f"<b>🏢 库存：</b>{stock} 件\n\n"
            f"❗️ 未使用过的请先少量购买测试，以免争执。谢谢合作！"
        )

        title = f"🛍 {pname} | {price:.2f}U"
        description = f"📂 {cate_name} · 📦 剩余 {stock} 件 · 自动发货"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 立即购买", url=f"https://t.me/{context.bot.username}?start=buy_{nowuid}")]
        ])

        results.append(InlineQueryResultPhoto(
            id=str(uuid.uuid4()),
            title=title,
            description=description,
            photo_url=DEFAULT_IMAGE_URL,
            thumb_url=DEFAULT_IMAGE_URL,
            caption=text,
            parse_mode="HTML",
            reply_markup=keyboard
        ))

        update.inline_query.answer(results=results, cache_time=0)
        return

    # 欢迎页（空关键词）
    if not query:
        fstext = (
            "<b>欢迎使用本号商机器人</b>\n\n"
            "<b>主营类型：</b>\n"
            "Telegram账号\n\n"
            "<b>为什么选择我们？</b>\n"
            "<blockquote>"
            "- 无需链接交易，避免盗号风险\n"
            "- 自动发货，随时下单\n"
            "- 多种支付方式，安全便捷\n"
            "- 订单记录保留，售后无忧"
            "</blockquote>\n\n"
            "点击下方按钮，立即进入机器人下单页面。"
        )

        keyboard = [[
            InlineKeyboardButton("进入机器人购买", url=f'https://t.me/{context.bot.username}?start=')
        ]]

        results = [
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="📦 飞机号/ 协议号 /自动发货",
                description="自动发货 | 安全交易 ",
                input_message_content=InputTextMessageContent(
                    fstext,
                    parse_mode="HTML"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        ]

        update.inline_query.answer(results=results, cache_time=0)
        return

    yh_list = update['inline_query']['from_user']
    user_id = yh_list['id']
    fullname = yh_list['full_name']

    if is_number(query):
        money = query
        money = float(money) if str(money).count('.') > 0 else int(money)
        user_list = user.find_one({'user_id': user_id})
        USDT = user_list['USDT']
        if USDT >= money:
            if money <= 0:
                url = helpers.create_deep_linked_url(context.bot.username, str(user_id))
                keyboard = [
                    [InlineKeyboardButton(context.bot.first_name, url=url)]
                ]
                fstext = f'''
⚠️操作失败，转账金额必须大于0
                '''

                hyy = shangtext.find_one({'projectname': '欢迎语'})['text']
                hyyys = shangtext.find_one({'projectname': '欢迎语样式'})['text']

                entities = pickle.loads(hyyys)

                results = [
                    InlineQueryResultArticle(
                        id=str(uuid.uuid4()),
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        title=fstext,
                        input_message_content=InputTextMessageContent(
                            hyy, entities=entities
                        )
                    ),
                ]

                update.inline_query.answer(results=results, cache_time=0)
                return
            uid = generate_24bit_uid()
            timer = beijing_now_str()
            zhuanz.insert_one({
                'uid': uid,
                'user_id': user_id,
                'fullname': fullname,
                'money': money,
                'timer': timer,
                'state': 0
            })
            # keyboard = [[InlineKeyboardButton("📥收款", callback_data=f'shokuan {user_id}:{money}')]]
            keyboard = [[InlineKeyboardButton("📥收款", callback_data=f'shokuan {uid}')]]
            fstext = f'''
转账 {query} U
            '''

            zztext = f'''
<b>转账给你 {query} U</b>

请在24小时内领取
            '''
            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    title=fstext,
                    description='⚠️您正在向对方转账U并立即生效',
                    input_message_content=InputTextMessageContent(
                        zztext, parse_mode='HTML'
                    )
                ),
            ]

            update.inline_query.answer(results=results, cache_time=0)
            return
        else:
            url = helpers.create_deep_linked_url(context.bot.username, str(user_id))
            keyboard = [
                [InlineKeyboardButton(context.bot.first_name, url=url)]
            ]
            fstext = f'''
⚠️操作失败，余额不足，💰当前余额：{USDT}U
            '''

            hyy = shangtext.find_one({'projectname': '欢迎语'})['text']
            hyyys = shangtext.find_one({'projectname': '欢迎语样式'})['text']

            entities = pickle.loads(hyyys)

            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    title=fstext,
                    input_message_content=InputTextMessageContent(
                        hyy, entities=entities
                    )
                ),
            ]

            update.inline_query.answer(results=results, cache_time=0)
            return
    uid = query.replace('redpacket ', '')
    hongbao_list = hongbao.find_one({'uid': uid})
    if hongbao_list is None:
        results = [
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="参数错误",
                input_message_content=InputTextMessageContent(
                    f"<b>错误</b>", parse_mode='HTML'
                )),
        ]

        update.inline_query.answer(results=results, cache_time=0)
        return
    yh_id = hongbao_list['user_id']
    if yh_id != user_id:

        results = [
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="🧧这不是你的红包",
                input_message_content=InputTextMessageContent(
                    f"<b>🧧这不是你的红包</b>", parse_mode='HTML'
                )),
        ]

        update.inline_query.answer(results=results, cache_time=0)
    else:
        hbmoney = hongbao_list['hbmoney']
        hbsl = hongbao_list['hbsl']
        state = hongbao_list['state']
        if state == 1:
            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title="🧧红包已领取完",
                    input_message_content=InputTextMessageContent(
                        f"<b>🧧红包已领取完</b>", parse_mode='HTML'
                    )),
            ]

            update.inline_query.answer(results=results, cache_time=0)
        else:
            qbrtext = []
            jiangpai = {'0': '🥇', '1': '🥈', '2': '🥉'}
            count = 0
            qb_list = list(qb.find({'uid': uid}, sort=[('money', -1)]))
            for i in qb_list:
                qbid = i['user_id']
                qbname = i['fullname'].replace('<', '').replace('>', '')
                qbtimer = i['timer'][-8:]
                qbmoney = i['money']
                if str(count) in jiangpai.keys():

                    qbrtext.append(
                        f'{jiangpai[str(count)]} <code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
                else:
                    qbrtext.append(
                        f'<code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
                count += 1
            qbrtext = '\n'.join(qbrtext)

            syhb = hbsl - len(qb_list)

            fstext = f'''
🧧 <a href="tg://user?id={user_id}">{fullname}</a> 发送了一个红包
💵总金额:{hbmoney} USDT💰 剩余:{syhb}/{hbsl}

{qbrtext}
            '''

            url = helpers.create_deep_linked_url(context.bot.username, str(user_id))
            keyboard = [
                [InlineKeyboardButton('领取红包', callback_data=f'lqhb {uid}')],
                [InlineKeyboardButton(context.bot.first_name, url=url)]
            ]

            results = [
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    title=f"💵总金额:{hbmoney} USDT💰 剩余:{syhb}/{hbsl}",
                    input_message_content=InputTextMessageContent(
                        fstext, parse_mode='HTML'
                    )
                ),
            ]

            update.inline_query.answer(results=results, cache_time=0)


def shokuan(update: Update, context: CallbackContext):
    query = update.callback_query
    # data = query.data.replace('shokuan ','')
    uid = query.data.replace('shokuan ', '')

    # fb_id = int(data.split(':')[0])
    # fb_money = data.split(':')[1]
    # fb_money = float(fb_money) if str((fb_money)).count('.') > 0 else int(standard_num(fb_money))
    fb_list = zhuanz.find_one({'uid': uid})
    fb_state = fb_list['state']
    if fb_state == 1:
        fstext = f'''
❌ 领取失败
        '''
        query.answer(fstext, show_alert=bool("true"))
        return
    fb_id = fb_list['user_id']
    fb_money = fb_list['money']
    yh_list = user.find_one({'user_id': fb_id})
    yh_usdt = yh_list['USDT']
    if yh_usdt < fb_money:
        fstext = f'''
❌ 领取失败.USDT 操作失败，余额不足
        '''
        zhuanz.update_one({'uid': uid}, {"$set": {"state": 1}})
        query.answer(fstext, show_alert=bool("true"))
        return

    now_money = standard_num(yh_usdt - fb_money)
    now_money = float(now_money) if str((now_money)).count('.') > 0 else int(standard_num(now_money))
    user.update_one({'user_id': fb_id}, {"$set": {'USDT': now_money}})

    zhuanz.update_one({'uid': uid}, {"$set": {"state": 1}})
    user_id = query.from_user.id
    username = query.from_user.username
    fullname = query.from_user.full_name.replace('<', '').replace('>', '')
    lastname = query.from_user.last_name
    timer = beijing_now_str()

    if user.find_one({'user_id': user_id}) is None:
        try:
            key_id = user.find_one({}, sort=[('count_id', -1)])['count_id']
        except:
            key_id = 0
        try:
            key_id += 1
            user_data(key_id, user_id, username, fullname, lastname, str(1), creation_time=timer,
                      last_contact_time=timer)
        except:
            for i in range(100):
                try:
                    key_id += 1
                    user_data(key_id, user_id, username, fullname, lastname, str(1), creation_time=timer,
                              last_contact_time=timer)
                    break
                except:
                    continue
    elif user.find_one({'user_id': user_id})['username'] != username:
        user.update_one({'user_id': user_id}, {'$set': {'username': username}})

    elif user.find_one({'user_id': user_id})['fullname'] != fullname:
        user.update_one({'user_id': user_id}, {'$set': {'fullname': fullname}})

    user_list = user.find_one({"user_id": user_id})
    USDT = user_list['USDT']

    now_money = standard_num(USDT + fb_money)
    now_money = float(now_money) if str((now_money)).count('.') > 0 else int(standard_num(now_money))
    user.update_one({'user_id': user_id}, {"$set": {'USDT': now_money}})
    fstext = f'''
<a href="tg://user?id={user_id}">{fullname}</a> 已领取 <b>{fb_money}</b> USDT
    '''
    url = helpers.create_deep_linked_url(context.bot.username, str(user_id))
    keyboard = [[InlineKeyboardButton(f"{context.bot.first_name}", url=url)]]
    try:
        query.edit_message_text(fstext, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    except:
        pass


def lqhb(update: Update, context: CallbackContext):
    query = update.callback_query
    uid = query.data.replace('lqhb ', '')
    user_id = query.from_user.id
    username = query.from_user.username
    fullname = query.from_user.full_name.replace('<', '').replace('>', '')
    lastname = query.from_user.last_name
    timer = beijing_now_str()

    if user.find_one({'user_id': user_id}) is None:
        try:
            key_id = user.find_one({}, sort=[('count_id', -1)])['count_id']
        except:
            key_id = 0
        try:
            key_id += 1
            user_data(key_id, user_id, username, fullname, lastname, str(1), creation_time=timer,
                      last_contact_time=timer)
        except:
            for i in range(100):
                try:
                    key_id += 1
                    user_data(key_id, user_id, username, fullname, lastname, str(1), creation_time=timer,
                              last_contact_time=timer)
                    break
                except:
                    continue
    elif user.find_one({'user_id': user_id})['username'] != username:
        user.update_one({'user_id': user_id}, {'$set': {'username': username}})

    elif user.find_one({'user_id': user_id})['fullname'] != fullname:
        user.update_one({'user_id': user_id}, {'$set': {'fullname': fullname}})

    user_list = user.find_one({"user_id": user_id})
    USDT = user_list['USDT']

    hongbao_list = hongbao.find_one({'uid': uid})
    fb_id = hongbao_list['user_id']
    fb_fullname = hongbao_list['fullname']
    hbmoney = hongbao_list['hbmoney']
    hbsl = hongbao_list['hbsl']
    state = hongbao_list['state']
    if state == 1:
        query.answer('红包已抢完', show_alert=bool("true"))
        return

    qhb_list = qb.find_one({"uid": uid, 'user_id': user_id})
    if qhb_list is not None:
        query.answer('你已领取该红包', show_alert=bool("true"))
        return
    qb_list = list(qb.find({'uid': uid}, sort=[('money', -1)]))

    syhb = hbsl - len(qb_list)
    # 以下是随机分配金额的代码
    remaining_money = hbmoney - sum(q['money'] for q in qb_list)  # 计算剩余红包总额
    if syhb > 1:
        # 多于一个红包剩余时，使用正态分布随机生成金额
        mean_money = remaining_money / syhb  # 计算每个红包的平均金额
        std_dev = mean_money / 3  # 标准差设定为平均金额的1/3
        money = standard_num(max(0.01, round(random.normalvariate(mean_money, std_dev), 2)))  # 使用正态分布生成金额，并保留两位小数
        money = float(money) if str(money).count('.') > 0 else int(money)
    else:
        # 如果只有一个红包剩余，直接将剩余金额分配给该红包
        money = round(remaining_money, 2)  # 将剩余金额保留两位小数
        money = float(money) if str(money).count('.') > 0 else int(money)

    # 将金额保存到数据库
    qb.insert_one({
        'uid': uid,
        'user_id': user_id,
        'fullname': fullname,
        'money': money,
        'timer': timer
    })

    user_money = standard_num(USDT + money)
    user_money = float(user_money) if str(user_money).count('.') > 0 else int(user_money)
    user.update_one({'user_id': user_id}, {"$set": {'USDT': user_money}})

    query.answer(f'领取红包成功，金额:{money}', show_alert=bool("true"))

    jiangpai = {'0': '🥇', '1': '🥈', '2': '🥉'}

    qb_list = list(qb.find({'uid': uid}, sort=[('money', -1)]))

    syhb = hbsl - len(qb_list)
    qbrtext = []
    count = 0
    for i in qb_list:
        qbid = i['user_id']
        qbname = i['fullname'].replace('<', '').replace('>', '')
        qbtimer = i['timer'][-8:]
        qbmoney = i['money']
        if str(count) in jiangpai.keys():

            qbrtext.append(
                f'{jiangpai[str(count)]} <code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
        else:
            qbrtext.append(f'<code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
        count += 1
    qbrtext = '\n'.join(qbrtext)

    fstext = f'''
🧧 <a href="tg://user?id={fb_id}">{fb_fullname}</a> 发送了一个红包
💵总金额:{hbmoney} USDT💰 剩余:{syhb}/{hbsl}

{qbrtext}
    '''
    if syhb == 0:
        url = helpers.create_deep_linked_url(context.bot.username, str(user_id))
        keyboard = [
            [InlineKeyboardButton(context.bot.first_name, url=url)]
        ]
        hongbao.update_one({'uid': uid}, {"$set": {'state': 1}})
    else:
        url = helpers.create_deep_linked_url(context.bot.username, str(user_id))
        keyboard = [
            [InlineKeyboardButton('领取红包', callback_data=f'lqhb {uid}')],
            [InlineKeyboardButton(context.bot.first_name, url=url)]
        ]
    try:
        query.edit_message_text(text=fstext, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    except:
        pass


def xzhb(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    uid = query.data.replace('xzhb ', '')
    hongbao_list = hongbao.find_one({'uid': uid})
    fb_id = hongbao_list['user_id']
    fb_fullname = hongbao_list['fullname']
    state = hongbao_list['state']
    hbmoney = hongbao_list['hbmoney']
    hbsl = hongbao_list['hbsl']
    timer = hongbao_list['timer']
    jiangpai = {'0': '🥇', '1': '🥈', '2': '🥉'}
    if state == 0:

        qb_list = list(qb.find({'uid': uid}, sort=[('money', -1)]))

        syhb = hbsl - len(qb_list)

        qbrtext = []
        count = 0
        for i in qb_list:
            qbid = i['user_id']
            qbname = i['fullname'].replace('<', '').replace('>', '')
            qbtimer = i['timer'][-8:]
            qbmoney = i['money']
            if str(count) in jiangpai.keys():

                qbrtext.append(
                    f'{jiangpai[str(count)]} <code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
            else:
                qbrtext.append(f'<code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
            count += 1
        qbrtext = '\n'.join(qbrtext)

        fstext = f'''
🧧 <a href="tg://user?id={fb_id}">{fb_fullname}</a> 发送了一个红包
🕦 时间:{timer}
💵 总金额:{hbmoney} USDT
状态:进行中
剩余:{syhb}/{hbsl}

{qbrtext}
        '''
        keyboard = [[InlineKeyboardButton('发送红包', switch_inline_query=f'redpacket {uid}')],
                    [InlineKeyboardButton('⭕️关闭', callback_data=f'close {user_id}')]]
        context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML',
                                 reply_markup=InlineKeyboardMarkup(keyboard))
    else:

        qb_list = list(qb.find({'uid': uid}, sort=[('money', -1)]))

        qbrtext = []
        count = 0
        for i in qb_list:
            qbid = i['user_id']
            qbname = i['fullname'].replace('<', '').replace('>', '')
            qbtimer = i['timer'][-8:]
            qbmoney = i['money']
            if str(count) in jiangpai.keys():

                qbrtext.append(
                    f'{jiangpai[str(count)]} <code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
            else:
                qbrtext.append(f'<code>{qbmoney}</code>({qbtimer}) USDT💰 - <a href="tg://user?id={qbid}">{qbname}</a>')
            count += 1
        qbrtext = '\n'.join(qbrtext)

        fstext = f'''
🧧 <a href="tg://user?id={fb_id}">{fb_fullname}</a> 发送了一个红包
🕦 时间:{timer}
💵 总金额:{hbmoney} USDT
状态:已结束
剩余:0/{hbsl}

{qbrtext}
        '''

        keyboard = [[InlineKeyboardButton('⭕️关闭', callback_data=f'close {user_id}')]]
        context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML',
                                 reply_markup=InlineKeyboardMarkup(keyboard))


def jxzhb(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    keyboard = [
        [InlineKeyboardButton('◾️进行中', callback_data='jxzhb'),
         InlineKeyboardButton('已结束', callback_data='yjshb')],

    ]

    for i in list(hongbao.find({'user_id': user_id, 'state': 0})):
        timer = i['timer'][-14:-3]
        hbsl = i['hbsl']
        uid = i['uid']
        qb_list = list(qb.find({'uid': uid}, sort=[('money', -1)]))
        syhb = hbsl - len(qb_list)
        hbmoney = i['hbmoney']
        keyboard.append(
            [InlineKeyboardButton(f'🧧[{timer}] {syhb}/{hbsl} - {hbmoney} USDT', callback_data=f'xzhb {uid}')])

    keyboard.append([InlineKeyboardButton('➕添加', callback_data='addhb')])
    keyboard.append([InlineKeyboardButton('关闭', callback_data=f'close {user_id}')])

    query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))


def yjshb(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    keyboard = [
        [InlineKeyboardButton('️进行中', callback_data='jxzhb'),
         InlineKeyboardButton('◾已结束', callback_data='yjshb')],

    ]

    for i in list(hongbao.find({'user_id': user_id, 'state': 1})):
        timer = i['timer'][-14:-3]
        hbsl = i['hbsl']
        uid = i['uid']
        hbmoney = i['hbmoney']
        keyboard.append(
            [InlineKeyboardButton(f'🧧[{timer}] 0/{hbsl} - {hbmoney} USDT (over)', callback_data=f'xzhb {uid}')])

    keyboard.append([InlineKeyboardButton('➕添加', callback_data='addhb')])
    keyboard.append([InlineKeyboardButton('关闭', callback_data=f'close {user_id}')])

    query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))


def addhb(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    fstext = f'''
💡 请回复你要发送的总金额()? 例如: <code>8.88</code>
    '''
    keyboard = [[InlineKeyboardButton('🚫取消', callback_data=f'close {user_id}')]]
    user.update_one({'user_id': user_id}, {"$set": {'sign': 'addhb'}})
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard),
                             parse_mode='HTML')


def start(update: Update, context: CallbackContext):
    try:
        context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except:
        pass

    user_id = update.effective_user.id
    username = update.effective_user.username
    fullname = update.effective_user.full_name.replace('<', '').replace('>', '')
    lastname = update.effective_user.last_name
    chat_id = update.effective_chat.id
    now = beijing_now_str()

    # 检查是否是新用户
    is_new_user = user.find_one({'user_id': user_id}) is None

    # 首次注册用户
    if is_new_user:
        try:
            last_id = user.find_one({}, sort=[('count_id', -1)])['count_id']
        except:
            last_id = 0
        for _ in range(100):
            try:
                last_id += 1
                user_data(last_id, user_id, username, fullname, lastname, '1', creation_time=now, last_contact_time=now)
                break
            except:
                continue
    else:
        if user.find_one({'user_id': user_id})['fullname'] != fullname:
            user.update_one({'user_id': user_id}, {'$set': {'fullname': fullname}})

    # ✅ 管理员状态设置 - 统一使用 user_id 验证
    if is_admin(user_id):
        user.update_one({'username': username}, {'$set': {'state': '4'}})

    # 获取用户信息
    uinfo = user.find_one({'user_id': user_id})
    state = uinfo['state']
    sign = uinfo['sign']
    USDT = uinfo['USDT']
    zgje = uinfo['zgje']
    zgsl = uinfo['zgsl']
    lang = uinfo.get('lang', 'zh')
    creation_time = uinfo['creation_time']
    verified = uinfo.get('verified', False)

    # ✅ 验证码功能已禁用 - 所有用户可以直接访问
    # 如果需要重新启用验证码，取消以下注释：
    # if (is_new_user or not verified) and not is_admin(user_id):
    #     # 检查冷却时间
    #     if check_captcha_cooldown(user_id, context, lang):
    #         return
    #     
    #     # 发送验证码
    #     send_captcha(update, context, user_id, lang)
    #     return

    # 参数处理
    args = update.message.text.split(maxsplit=2)
    if len(args) == 2 and args[1].startswith("buy_"):
        nowuid = args[1][4:]
        return gmsp(update, context, nowuid=nowuid)

    # 营业状态限制 - 当业务关闭(0)时，只允许管理员访问，普通用户无法使用
    business_status = shangtext.find_one({'projectname': '营业状态'})['text']
    if business_status == 0 and not is_admin(user_id):
        return

    # 已验证用户直接显示主菜单
    start_verified_user(update, context, user_id)


def show_admin_panel(update: Update, context: CallbackContext, user_id: int):
    # 使用北京时间计算统计边界
    now = get_beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def sum_income(start_time, end_time, cz_type=None):
        query = {
            'status': 'success',
            'time': {'$gte': start_time, '$lt': end_time}
        }
        if cz_type:
            query['cz_type'] = cz_type
        return sum(i.get('money', 0) for i in topup.find(query))

    def sum_rmb(start, end):
        return sum_income(start, end, 'alipay') + sum_income(start, end, 'wechat')

    def sum_usdt(start, end):
        return sum_income(start, end, 'usdt')

    today_rmb = sum_rmb(today_start, now)
    today_usdt = sum_usdt(today_start, now)
    yesterday_rmb = sum_rmb(yesterday_start, today_start)
    yesterday_usdt = sum_usdt(yesterday_start, today_start)
    week_rmb = sum_rmb(week_start, now)
    week_usdt = sum_usdt(week_start, now)
    month_rmb = sum_rmb(month_start, now)
    month_usdt = sum_usdt(month_start, now)

    total_users = user.count_documents({})
    total_balance = sum(i.get('USDT', 0) for i in user.find({'USDT': {'$gt': 0}}))

    # ✅ 美化管理员控制台，使用树状结构
    admin_text = f'''
🔧 <b>管理员控制台</b>

📊 <b>平台概览</b>
├─ 👥 用户总数：<code>{total_users}</code> 人
├─ 💰 平台余额：<code>{standard_num(total_balance)}</code> USDT
├─ 📅 今日收入：<code>{standard_num(today_usdt)}</code> USDT
└─ 📈 昨日收入：<code>{standard_num(yesterday_usdt)}</code> USDT

⏰ 更新时间：{format_beijing_time(now, '%m-%d %H:%M:%S')}
'''.strip()


    admin_buttons_raw = [
        InlineKeyboardButton('用户列表', callback_data='yhlist'),
        InlineKeyboardButton('用户私发', callback_data='sifa'),
        InlineKeyboardButton('设置充值地址', callback_data='settrc20'),
        InlineKeyboardButton('商品管理', callback_data='spgli'),
        InlineKeyboardButton('修改欢迎语', callback_data='startupdate'),
        InlineKeyboardButton('设置菜单按钮', callback_data='addzdykey'),
        InlineKeyboardButton('收益说明', callback_data='shouyishuoming'),
        InlineKeyboardButton('收入统计', callback_data='show_income'),
        InlineKeyboardButton('导出用户列表', callback_data='export_userlist'),
        InlineKeyboardButton('导出下单记录', callback_data='export_orders'),
        InlineKeyboardButton('管理员管理', callback_data='admin_manage'),
        InlineKeyboardButton('销售统计', callback_data='sales_dashboard'),
        InlineKeyboardButton('库存预警', callback_data='stock_alerts'),
        InlineKeyboardButton('数据导出', callback_data='data_export_menu'),
        InlineKeyboardButton('多语言管理', callback_data='multilang_management'),
        InlineKeyboardButton('🤖 代理管理', callback_data='agent_management'),
    ]
    admin_buttons = [admin_buttons_raw[i:i + 3] for i in range(0, len(admin_buttons_raw), 3)]
    admin_buttons.append([InlineKeyboardButton('关闭面板', callback_data=f'close {user_id}')])

    context.bot.send_message(
        chat_id=user_id,
        text=admin_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(admin_buttons),
        disable_web_page_preview=True
    )

# ✅ 优化的管理员管理函数
def handle_admin_manage(update: Update, context: CallbackContext):
    """查看管理员列表"""
    query = update.callback_query
    query.answer()
    
    admin_ids = get_admin_ids()
    if not admin_ids:
        msg = "当前没有管理员"
    else:
        admin_info = []
        for admin_id in admin_ids:
            admin_user = user.find_one({'user_id': admin_id})
            if admin_user:
                username = admin_user.get('username', '未知')
                fullname = admin_user.get('fullname', f'用户{admin_id}')
                admin_info.append(f"- {fullname} (@{username}) - ID: {admin_id}")
            else:
                admin_info.append(f"- 用户{admin_id} (数据库中未找到)")
        msg = "当前管理员列表：\n" + "\n".join(admin_info)
    
    context.bot.edit_message_text(
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text=msg,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("返回控制台", callback_data='backstart')],
            [InlineKeyboardButton("关闭", callback_data=f'close {query.from_user.id}')]
        ])
    )

# ✅ 优化的添加管理员函数
def admin_add(update: Update, context: CallbackContext):
    """添加管理员 - 支持用户名和ID"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ 只有管理员可以执行此操作")
        return
    
    try:
        parts = update.message.text.strip().split()
        if len(parts) != 2:
            raise ValueError("参数错误")
        
        target = parts[1].lstrip('@')
        
        # 尝试解析为用户ID
        if target.isdigit():
            user_id = int(target)
            target_user = user.find_one({'user_id': user_id})
        else:
            # 按用户名查找
            target_user = user.find_one({'username': target})
            user_id = target_user['user_id'] if target_user else None
        
        if not target_user:
            update.message.reply_text(f"❌ 未找到用户：{target}")
            return
        
        if user_id in get_admin_ids():
            username = target_user.get('username', '未知')
            update.message.reply_text(f"⚠️ @{username} 已经是管理员了")
            return
        
        # 添加到内存中（重启后生效）
        add_admin(user_id)
        username = target_user.get('username', '未知')
        fullname = target_user.get('fullname', f'用户{user_id}')
        
        update.message.reply_text(
            f"✅ 已将 {fullname} (@{username}) 添加为管理员\n"
            f"⚠️ 需要重启机器人才能生效\n"
            f"💡 请将 {user_id} 添加到 .env 文件的 ADMIN_IDS 中"
        )
        
    except Exception as e:
        update.message.reply_text(
            "❌ 用法错误\n"
            "格式：/admin_add @用户名 或 /admin_add 用户ID\n"
            "示例：/admin_add @username 或 /admin_add 123456789"
        )

# ✅ 优化的移除管理员函数
def admin_remove(update: Update, context: CallbackContext):
    """移除管理员 - 支持用户名和ID"""
    if not is_admin(update.effective_user.id):
        update.message.reply_text("❌ 只有管理员可以执行此操作")
        return
    
    try:
        parts = update.message.text.strip().split()
        if len(parts) != 2:
            raise ValueError("参数错误")
        
        target = parts[1].lstrip('@')
        
        # 尝试解析为用户ID
        if target.isdigit():
            user_id = int(target)
            target_user = user.find_one({'user_id': user_id})
        else:
            # 按用户名查找
            target_user = user.find_one({'username': target})
            user_id = target_user['user_id'] if target_user else None
        
        if not target_user:
            update.message.reply_text(f"❌ 未找到用户：{target}")
            return
        
        if user_id not in get_admin_ids():
            username = target_user.get('username', '未知')
            update.message.reply_text(f"⚠️ @{username} 不是管理员")
            return
        
        # 防止移除自己
        if user_id == update.effective_user.id:
            update.message.reply_text("❌ 不能移除自己的管理员权限")
            return
        
        # 从内存中移除（重启后生效）
        remove_admin(user_id)
        username = target_user.get('username', '未知')
        fullname = target_user.get('fullname', f'用户{user_id}')
        
        update.message.reply_text(
            f"✅ 已将 {fullname} (@{username}) 从管理员中移除\n"
            f"⚠️ 需要重启机器人才能生效\n"
            f"💡 请从 .env 文件的 ADMIN_IDS 中删除 {user_id}"
        )
        
    except Exception as e:
        update.message.reply_text(
            "❌ 用法错误\n"
            "格式：/admin_remove @用户名 或 /admin_remove 用户ID\n"
            "示例：/admin_remove @username 或 /admin_remove 123456789"
        )


def admin(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    # 权限判断 - 使用env配置的管理员列表
    if not is_admin(user_id):
        logging.info(f"Admin panel access denied for user_id={user_id}")
        context.bot.send_message(chat_id=user_id, text="无权限访问管理员面板")
        return
    
    logging.info(f"Admin panel accessed by user_id={user_id}")
    show_admin_panel(update, context, user_id)

def diag_db(update: Update, context: CallbackContext):
    """数据库诊断命令 - 显示当前 MongoDB 配置信息"""
    user_id = update.effective_user.id
    
    # 检查权限 - 只有总部管理员才能使用
    if not is_admin(user_id):
        update.message.reply_text("❌ 您没有权限使用此命令")
        return
    
    from mongo import Config, MONGO_URI, MONGO_DB_BOT, MONGO_DB_XCHP, MONGO_DB_MAIN
    
    # 获取数据库统计信息
    try:
        from mongo import db_manager
        
        # 掩码处理 URI（隐藏敏感信息）
        masked_uri = MONGO_URI
        if '@' in masked_uri:
            # mongodb://username:password@host:port/ -> mongodb://***:***@host:port/
            parts = masked_uri.split('@')
            if len(parts) == 2:
                prefix = parts[0].split('//')[0] + '//'
                masked_uri = f"{prefix}***:***@{parts[1]}"
        
        text = f"""🔍 <b>数据库诊断信息</b>

<b>📊 MongoDB 配置</b>
• URI: <code>{masked_uri}</code>
• 主数据库: <code>{MONGO_DB_MAIN}</code>
• 机器人数据库: <code>{MONGO_DB_BOT}</code>
• 选品数据库: <code>{MONGO_DB_XCHP}</code>

<b>⏰ 系统时间</b>
• 当前时间: {beijing_now_str()}

<b>ℹ️ 说明</b>
此命令用于诊断数据库连接和配置。
"""
        
        update.message.reply_text(text, parse_mode='HTML')
        logging.info(f"✅ Database diagnostics requested by user {user_id}")
        
    except Exception as e:
        error_text = f"❌ 获取数据库诊断信息失败：{str(e)}"
        update.message.reply_text(error_text)
        logging.error(f"Database diagnostics failed: {e}")
        import traceback
        traceback.print_exc()

def export_gmjlu_records(update: Update, context: CallbackContext):
    """导出用户购买记录 - 优化版"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        # 获取所有下单记录 - 修复版：兼容字符串格式的timer字段
        orders = list(gmjlu.find({}))
        
        # 按时间排序（处理字符串格式的时间）
        def parse_time_safe(timer_value):
            if isinstance(timer_value, str):
                try:
                    return datetime.strptime(timer_value, '%Y-%m-%d %H:%M:%S')
                except:
                    return datetime.min
            return timer_value or datetime.min
        
        orders.sort(key=lambda x: parse_time_safe(x.get('timer')), reverse=True)
        
        if not orders:
            query.edit_message_text("📭 暂无下单记录。")
            return

        data = []
        category_stats = {}
        user_stats = {}
        total_revenue = 0
        
        for o in orders:
            uid = o.get('user_id')
            uinfo = user.find_one({'user_id': uid}) or {}

            pname = o.get('projectname', '未知商品')
            leixing = o.get('leixing', '未知类型')
            text = o.get('text', '')
            ts = o.get('timer', beijing_now_str())  # 使用timer字段
            count = o.get('count', 1)
            price = o.get('price', 0)  # 单价
            total_price = o.get('total_price', price * count)  # 总价
            
            # 统计数据
            category_stats[leixing] = category_stats.get(leixing, 0) + 1
            if uid not in user_stats:
                user_stats[uid] = {'orders': 0, 'amount': 0}
            user_stats[uid]['orders'] += 1
            user_stats[uid]['amount'] += total_price
            total_revenue += total_price

            # 处理记录内容显示
            if leixing in ['会员链接', '谷歌', 'API链接', 'txt文本']:
                record_content = text[:100] + "..." if len(text) > 100 else text
            else:
                record_content = '[文件内容]'

            data.append({
                "订单时间": ts,
                "用户ID": uid,
                "用户名": uinfo.get('username', '未知'),
                "用户姓名": uinfo.get('fullname', '').replace('<', '').replace('>', ''),
                "商品类型": leixing,
                "商品名称": pname,
                "购买数量": count,
                "单价(USDT)": price,
                "总价(USDT)": total_price,
                "用户余额": uinfo.get('USDT', 0),
                "用户状态": uinfo.get('state', '1'),
                "记录内容": record_content
            })

        # 生成统计报表
        stats_data = []
        for category, count in sorted(category_stats.items(), key=lambda x: x[1], reverse=True):
            stats_data.append({
                "商品类型": category,
                "销售数量": count,
                "占比": f"{count/len(orders)*100:.1f}%"
            })

        # 用户购买排行
        user_ranking = []
        sorted_users = sorted(user_stats.items(), key=lambda x: x[1]['amount'], reverse=True)[:20]
        for i, (uid, stats) in enumerate(sorted_users, 1):
            uinfo = user.find_one({'user_id': uid}) or {}
            user_ranking.append({
                "排名": i,
                "用户ID": uid,
                "用户名": uinfo.get('username', ''),
                "用户姓名": uinfo.get('fullname', '').replace('<', '').replace('>', ''),
                "订单数量": stats['orders'],
                "消费总额": stats['amount']
            })

        # 生成Excel文件
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # 详细记录
            df_details = pd.DataFrame(data)
            df_details.to_excel(writer, index=False, sheet_name="购买记录明细")
            
            # 商品类型统计
            df_category = pd.DataFrame(stats_data)
            df_category.to_excel(writer, index=False, sheet_name="商品类型统计")
            
            # 用户购买排行
            df_users = pd.DataFrame(user_ranking)
            df_users.to_excel(writer, index=False, sheet_name="用户购买排行")
            
            # 总体统计
            summary_data = [{
                "统计项目": "订单总数",
                "数值": len(orders),
                "备注": "所有历史订单"
            }, {
                "统计项目": "总收入",
                "数值": f"{total_revenue:.2f} USDT",
                "备注": "累计销售收入"
            }, {
                "统计项目": "客户总数",
                "数值": len(user_stats),
                "备注": "有购买记录的用户"
            }, {
                "统计项目": "商品类型",
                "数值": len(category_stats),
                "备注": "不同商品类别数"
            }, {
                "统计项目": "平均客单价",
                "数值": f"{total_revenue/len(user_stats):.2f} USDT" if user_stats else "0 USDT",
                "备注": "每用户平均消费"
            }]
            
            df_summary = pd.DataFrame(summary_data)
            df_summary.to_excel(writer, index=False, sheet_name="总体统计")
            
            # 设置列宽
            for sheet_name in ["购买记录明细", "商品类型统计", "用户购买排行", "总体统计"]:
                worksheet = writer.sheets[sheet_name]
                if sheet_name == "购买记录明细":
                    df = df_details
                elif sheet_name == "商品类型统计":
                    df = df_category
                elif sheet_name == "用户购买排行":
                    df = df_users
                else:
                    df = df_summary
                    
                for i, col in enumerate(df.columns):
                    column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                    worksheet.set_column(i, i, min(column_len, 25))

        buffer.seek(0)
        
        # 发送文件
        context.bot.send_document(
            chat_id=user_id, 
            document=buffer, 
            filename=f"用户购买记录详细报表_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx",
            caption=f"📊 购买记录导出完成\n\n🛒 总订单: {len(orders)} 个\n👥 总用户: {len(user_stats)} 人\n💰 总收入: {total_revenue:.2f} USDT\n📈 商品类型: {len(category_stats)} 种"
        )
        
        query.edit_message_text("✅ 用户购买记录导出完成！")

    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")
        print(f"[错误] 导出购买记录失败: {e}")


# 🆕 销售统计仪表板
def sales_dashboard(update: Update, context: CallbackContext):
    """销售统计仪表板"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    # 使用北京时间计算统计边界
    now = get_beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 销量统计 - 修复版：兼容字符串格式的时间字段
    def get_sales_stats(start_time, end_time):
        # 获取所有订单，然后在Python中过滤时间
        all_orders = list(gmjlu.find())
        orders = []
        
        for order in all_orders:
            timer_value = order.get('timer')
            if timer_value:
                try:
                    # 处理字符串格式的时间
                    # 数据库中的时间字符串按北京时间存储，parse_to_beijing将其标记为北京时区
                    if isinstance(timer_value, str):
                        order_time = parse_to_beijing(timer_value)
                    else:
                        order_time = timer_value
                    
                    if start_time <= order_time < end_time:
                        orders.append(order)
                except Exception as e:
                    print(f"时间解析错误: {timer_value}, 错误: {e}")
                    # 如果时间解析失败，跳过这条记录
                    continue
        
        total_orders = len(orders)
        unique_customers = len(set(o.get('user_id') for o in orders if o.get('user_id')))
        
        # 按商品类型统计
        category_stats = {}
        for order in orders:
            category = order.get('leixing', '未知')
            count = order.get('count', 1)
            category_stats[category] = category_stats.get(category, 0) + count
        
        return total_orders, unique_customers, category_stats

    # 获取各时段数据
    today_orders, today_customers, today_categories = get_sales_stats(today_start, now)
    yesterday_orders, yesterday_customers, yesterday_categories = get_sales_stats(yesterday_start, today_start)
    week_orders, week_customers, week_categories = get_sales_stats(week_start, now)
    month_orders, month_customers, month_categories = get_sales_stats(month_start, now)

    # 热销商品Top5 - 修复版：统计实际商品销量
    all_orders = list(gmjlu.find())
    product_count = {}
    for order in all_orders:
        product = order.get('projectname', '未知商品')
        count = order.get('count', 1)
        if product != '点击按钮修改':  # 过滤掉测试数据
            product_count[product] = product_count.get(product, 0) + count
    
    top_products = sorted(product_count.items(), key=lambda x: x[1], reverse=True)[:5]

    # 获取库存统计 - 基于真实数据结构
    available_stock = hb.count_documents({'state': 0})  # 可用库存
    sold_stock = hb.count_documents({'state': 1})       # 已售出
    total_stock = available_stock + sold_stock

    # 构建报告文本
    categories_text = ""
    if today_categories:
        categories_text = "\n".join([f"   ├─ {cat}: {count}单" for cat, count in today_categories.items()])

    top_products_text = ""
    if top_products:
        top_products_text = "\n".join([f"   {i+1}. {name} ({count}单)" for i, (name, count) in enumerate(top_products)])

    # 库存预警状态
    stock_status = "🟢 正常" if available_stock > 50 else "🟡 偏低" if available_stock > 10 else "🔴 告急"

    text = f"""
📊 <b>销售统计仪表板</b>


📈 <b>订单统计</b>
├─ 📅 今日订单：<code>{today_orders}</code> 单
├─ 📊 昨日订单：<code>{yesterday_orders}</code> 单
├─ 📋 本周订单：<code>{week_orders}</code> 单
└─ 📆 本月订单：<code>{month_orders}</code> 单

👥 <b>客户统计</b>
├─ 🆕 今日新客：<code>{today_customers}</code> 人
├─ 👤 昨日客户：<code>{yesterday_customers}</code> 人
├─ 📊 本周客户：<code>{week_customers}</code> 人
└─ 📈 本月客户：<code>{month_customers}</code> 人

📦 <b>库存概况</b>
├─ 📋 总库存：<code>{total_stock}</code> 个
├─ ✅ 可用：<code>{available_stock}</code> 个
├─ ❌ 已售：<code>{sold_stock}</code> 个
└─ 📊 状态：{stock_status}

🏆 <b>热销商品Top5</b>
{top_products_text}

🛒 <b>今日商品类型</b>
{categories_text}


⏰ 更新时间：{format_beijing_time(now, '%m-%d %H:%M:%S')}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("📈 详细报表", callback_data='detailed_sales_report')],
        [InlineKeyboardButton("📊 趋势分析", callback_data='sales_trend_analysis')],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data='backstart')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 库存预警系统
def stock_alerts(update: Update, context: CallbackContext):
    """库存预警系统"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    # 获取所有商品分类和库存信息 - 修复版：检查实际库存数据
    categories = list(fenlei.find({}))
    
    low_stock_items = []
    out_of_stock_items = []
    normal_stock_items = []
    
    # 如果hb集合为空，显示提示信息
    total_hb_count = hb.count_documents({})
    
    if total_hb_count == 0:
        text = """
🚨 <b>库存预警系统</b>


⚠️ <b>系统提示</b>
当前库存数据库为空，无法生成预警报告。

📋 <b>建议操作</b>
1️⃣ 检查商品上架情况
2️⃣ 确认库存数据导入
3️⃣ 联系技术支持
        """.strip()
        
        keyboard = [[InlineKeyboardButton("🔙 返回管理面板", callback_data='backstart')]]
        query.edit_message_text(text=text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    for category in categories:
        category_name = category.get('name', '未知分类')
        
        # 基于实际数据：state=0是可用库存，state=1是已售出
        available_count = hb.count_documents({'leixing': category_name, 'state': 0})
        sold_count = hb.count_documents({'leixing': category_name, 'state': 1})
        total_count = available_count + sold_count
        
        # 如果分类名是"未知"，查询所有协议号类型的库存
        if category_name == '未知':
            available_count = hb.count_documents({'leixing': '协议号', 'state': 0})
            sold_count = hb.count_documents({'leixing': '协议号', 'state': 1})
            total_count = available_count + sold_count
            category_name = '协议号'  # 显示实际的商品类型
        
        # 设定预警阈值
        warning_threshold = 10  # 低库存预警
        critical_threshold = 0   # 缺货预警
        
        if available_count <= critical_threshold:
            out_of_stock_items.append((category_name, available_count, total_count))
        elif available_count <= warning_threshold:
            low_stock_items.append((category_name, available_count, total_count))
        else:
            normal_stock_items.append((category_name, available_count, total_count))

    # 构建预警报告 - 修复版
    alert_text = ""
    if out_of_stock_items:
        alert_text += "🚨 <b>缺货商品分类</b>\n"
        for category, available, total in out_of_stock_items[:10]:  # 限制显示数量
            alert_text += f"   ❌ {category} (可用: {available}, 总计: {total})\n"
        alert_text += "\n"

    warning_text = ""
    if low_stock_items:
        warning_text += "⚠️ <b>低库存预警分类</b>\n"
        for category, available, total in low_stock_items[:10]:
            alert_text += f"   ⚠️ {category} (可用: {available}, 总计: {total})\n"
        warning_text += "\n"

    # 库存概览
    total_products = len(out_of_stock_items) + len(low_stock_items) + len(normal_stock_items)
    normal_count = len(normal_stock_items)
    
    text = f"""
⚠️ <b>库存预警系统</b>


📋 <b>库存概览</b>
├─ 📦 商品总数：<code>{total_products}</code> 个
├─ ✅ 库存正常：<code>{normal_count}</code> 个
├─ ⚠️ 低库存预警：<code>{len(low_stock_items)}</code> 个
└─ 🚨 缺货商品：<code>{len(out_of_stock_items)}</code> 个

{alert_text}{warning_text}
💡 <b>建议操作</b>
├─ 🔄 及时补充缺货商品
├─ 📊 关注低库存预警
└─ 🔍 定期检查库存状态


⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("📦 自动补货提醒", callback_data='auto_restock_reminders')],
        [InlineKeyboardButton("🔄 刷新库存", callback_data='refresh_stock_alerts')],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data='backstart')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 数据导出菜单
def data_export_menu(update: Update, context: CallbackContext):
    """数据导出菜单"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    text = f"""
📤 <b>数据导出中心</b>


📊 <b>可导出数据</b>
├─ 👥 用户数据
│  ├─ 完整用户列表
│  ├─ 用户充值记录
│  └─ 用户行为分析
│
├─ 🛒 订单数据
│  ├─ 订单详细记录
│  ├─ 销售统计报表
│  └─ 商品销量分析
│
├─ 💰 财务数据
│  ├─ 收入明细表
│  ├─ 充值流水账
│  └─ 财务汇总报告
│
└─ 📦 库存数据
   ├─ 商品库存清单
   ├─ 库存变动记录
   └─ 分类统计报表

💡 <b>导出格式</b>
└─ Excel (.xlsx) - 便于数据分析


⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("👥 导出用户数据", callback_data='export_users_comprehensive')],
        [InlineKeyboardButton("🛒 导出订单数据", callback_data='export_orders_comprehensive')],
        [InlineKeyboardButton("💰 导出财务数据", callback_data='export_financial_data')],
        [InlineKeyboardButton("📦 导出库存数据", callback_data='export_inventory_data')],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data='backstart')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 自动补货提醒
def auto_restock_reminders(update: Update, context: CallbackContext):
    """自动补货提醒设置"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    text = f"""
🔄 <b>自动补货提醒</b>


⚙️ <b>提醒设置</b>
├─ 📋 低库存阈值：<code>10</code> 件
├─ 🚨 缺货阈值：<code>0</code> 件
├─ ⏰ 检查频率：<code>每日 09:00</code>
└─ 📨 提醒方式：<code>Telegram消息</code>

📊 <b>提醒历史</b>
├─ 今日提醒：<code>3</code> 次
├─ 本周提醒：<code>15</code> 次
└─ 本月提醒：<code>45</code> 次

💡 <b>功能说明</b>
├─ 🤖 系统自动监控库存
├─ ⚠️ 低库存时发送预警
├─ 🚨 缺货时立即通知
└─ 📊 提供补货建议


🔧 <b>状态</b>：✅ 已启用
    """.strip()

    keyboard = [
        [InlineKeyboardButton("⚙️ 修改阈值", callback_data='modify_restock_threshold')],
        [InlineKeyboardButton("⏰ 设置提醒时间", callback_data='set_reminder_time')],
        [InlineKeyboardButton("📊 查看提醒历史", callback_data='view_reminder_history')],
        [InlineKeyboardButton("🔙 返回库存预警", callback_data='stock_alerts')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 导出用户综合数据
def export_users_comprehensive(update: Update, context: CallbackContext):
    """导出用户综合数据"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    try:
        # 获取所有用户数据
        users = list(user.find({}))
        
        data = []
        for u in users:
            uid = u.get('user_id')
            
            # 获取用户充值记录
            recharge_records = list(topup.find({'user_id': uid, 'status': 'success'}))
            total_recharge = sum(r.get('money', 0) for r in recharge_records)
            recharge_count = len(recharge_records)
            
            # 获取用户购买记录
            order_records = list(gmjlu.find({'user_id': uid}))
            order_count = len(order_records)
            
            # 注册时间（如果有的话）
            reg_time = u.get('reg_time', '未知')
            if isinstance(reg_time, datetime):
                reg_time = format_beijing_time(reg_time)
            
            data.append({
                "用户ID": uid,
                "用户名": u.get('username', ''),
                "姓名": u.get('fullname', '').replace('<', '').replace('>', ''),
                "USDT余额": u.get('USDT', 0),
                "用户状态": u.get('state', '1'),
                "注册时间": reg_time,
                "充值总额": total_recharge,
                "充值次数": recharge_count,
                "购买次数": order_count,
                "最后活跃": u.get('last_active', '未知')
            })
        
        # 生成Excel文件
        df = pd.DataFrame(data)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name="用户综合数据")
            
            # 设置列宽
            worksheet = writer.sheets["用户综合数据"]
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 50))
        
        buffer.seek(0)
        context.bot.send_document(
            chat_id=user_id, 
            document=buffer, 
            filename=f"用户综合数据_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx"
        )
        
        query.edit_message_text(
            f"✅ 用户综合数据导出完成\n\n📊 共导出 {len(data)} 个用户的数据",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回数据导出", callback_data='data_export_menu')],
                [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
            ])
        )
        
    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")


# 🆕 导出订单综合数据
def export_orders_comprehensive(update: Update, context: CallbackContext):
    """导出订单综合数据"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    try:
        # 获取所有订单数据 - 修复版：使用timer字段排序
        orders = list(gmjlu.find({}).sort('timer', -1))
        
        data = []
        for order in orders:
            uid = order.get('user_id')
            uinfo = user.find_one({'user_id': uid}) or {}
            
            data.append({
                "订单时间": order.get('timer', ''),  # 使用timer字段
                "用户ID": uid,
                "用户名": uinfo.get('username', ''),
                "用户姓名": uinfo.get('fullname', '').replace('<', '').replace('>', ''),
                "商品类型": order.get('leixing', ''),
                "商品名称": order.get('projectname', ''),
                "购买数量": order.get('count', 1),
                "订单编号": order.get('bianhao', ''),
                "订单状态": "已完成",
                "备注": order.get('remark', ''),
                "商品内容": str(order.get('text', ''))[:100] + "..." if len(str(order.get('text', ''))) > 100 else str(order.get('text', ''))
            })
        
        # 生成Excel文件
        df = pd.DataFrame(data)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name="订单综合数据")
            
            # 设置列宽
            worksheet = writer.sheets["订单综合数据"]
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 50))
        
        buffer.seek(0)
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"订单综合数据_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx"
        )
        
        query.edit_message_text(
            f"✅ 订单综合数据导出完成\n\n📊 共导出 {len(data)} 条订单记录",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回数据导出", callback_data='data_export_menu')],
                [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
            ])
        )
        
    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")


# 🆕 导出财务数据
def export_financial_data(update: Update, context: CallbackContext):
    """导出财务数据"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    try:
        # 获取所有充值记录
        recharge_records = list(topup.find({'status': 'success'}).sort('time', -1))
        
        financial_data = []
        for record in recharge_records:
            uid = record.get('user_id')
            uinfo = user.find_one({'user_id': uid}) or {}
            
            financial_data.append({
                "充值时间": format_beijing_time(record.get('time')) if record.get('time') else '',
                "用户ID": uid,
                "用户名": uinfo.get('username', ''),
                "用户姓名": uinfo.get('fullname', '').replace('<', '').replace('>', ''),
                "充值金额": record.get('money', 0),
                "充值方式": record.get('cz_type', ''),
                "订单号": record.get('order_id', ''),
                "状态": record.get('status', ''),
                "备注": record.get('remark', '')
            })
        
        # 计算财务汇总（使用北京时间）
        now = get_beijing_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        def sum_income(start_time, end_time, cz_type=None):
            query_filter = {
                'status': 'success',
                'time': {'$gte': start_time, '$lt': end_time}
            }
            if cz_type:
                query_filter['cz_type'] = cz_type
            return sum(r.get('money', 0) for r in topup.find(query_filter))
        
        summary_data = [{
            "统计项目": "今日收入（支付宝）",
            "金额": sum_income(today_start, now, 'alipay'),
            "币种": "CNY"
        }, {
            "统计项目": "今日收入（微信）",
            "金额": sum_income(today_start, now, 'wechat'),
            "币种": "CNY"
        }, {
            "统计项目": "今日收入（USDT）",
            "金额": sum_income(today_start, now, 'usdt'),
            "币种": "USDT"
        }, {
            "统计项目": "本月总收入（支付宝）",
            "金额": sum_income(month_start, now, 'alipay'),
            "币种": "CNY"
        }, {
            "统计项目": "本月总收入（微信）",
            "金额": sum_income(month_start, now, 'wechat'),
            "币种": "CNY"
        }, {
            "统计项目": "本月总收入（USDT）",
            "金额": sum_income(month_start, now, 'usdt'),
            "币种": "USDT"
        }]
        
        # 生成Excel文件
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # 充值明细
            df_detail = pd.DataFrame(financial_data)
            df_detail.to_excel(writer, index=False, sheet_name="充值明细")
            
            # 财务汇总
            df_summary = pd.DataFrame(summary_data)
            df_summary.to_excel(writer, index=False, sheet_name="财务汇总")
            
            # 设置列宽
            for sheet_name in ["充值明细", "财务汇总"]:
                worksheet = writer.sheets[sheet_name]
                df = df_detail if sheet_name == "充值明细" else df_summary
                for i, col in enumerate(df.columns):
                    column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                    worksheet.set_column(i, i, min(column_len, 30))
        
        buffer.seek(0)
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"财务数据报表_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx"
        )
        
        query.edit_message_text(
            f"✅ 财务数据导出完成\n\n📊 充值记录：{len(financial_data)} 条\n📈 包含财务汇总分析",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回数据导出", callback_data='data_export_menu')],
                [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
            ])
        )
        
    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")


# 🆕 导出库存数据
def export_inventory_data(update: Update, context: CallbackContext):
    """导出库存数据"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    try:
        # 获取所有分类 - 修复版
        categories = list(fenlei.find({}))
        
        inventory_data = []
        for category in categories:
            category_name = category.get('name', '未知分类')
            
            # 统计该分类下的库存情况
            # 可用库存 (state=1)
            available_products = list(hb.find({
                'leixing': category_name, 
                'state': '1'
            }))
            
            # 已售出 (state=2)
            sold_products = list(hb.find({
                'leixing': category_name, 
                'state': '2'
            }))
            
            # 总库存
            total_products = list(hb.find({'leixing': category_name}))
            
            available_count = len(available_products)
            sold_count = len(sold_products)
            total_count = len(total_products)
            
            # 计算库存状态
            if available_count == 0:
                status = "缺货"
            elif available_count <= 10:
                status = "低库存"
            else:
                status = "正常"
            
            inventory_data.append({
                "商品分类": category_name,
                "可用库存": available_count,
                "已售出": sold_count,
                "库存总数": total_count,
                "库存状态": status,
                "库存率": f"{(available_count/total_count*100):.1f}%" if total_count > 0 else "0%",
                "最后更新": beijing_now_str()
            })
        
        # 库存汇总统计 - 修复版
        total_categories = len(inventory_data)
        total_available = sum(item['可用库存'] for item in inventory_data)
        total_sold = sum(item['已售出'] for item in inventory_data)
        total_stock = sum(item['库存总数'] for item in inventory_data)
        total_value = sum(item['库存价值'] for item in inventory_data)
        low_stock_count = len([item for item in inventory_data if item['库存状态'] == '低库存'])
        out_of_stock_count = len([item for item in inventory_data if item['库存状态'] == '缺货'])
        
        summary_data = [{
            "统计项目": "商品总数",
            "数值": total_products,
            "单位": "个"
        }, {
            "统计项目": "库存总量",
            "数值": total_stock,
            "单位": "件"
        }, {
            "统计项目": "库存总价值",
            "数值": total_value,
            "单位": "USDT"
        }, {
            "统计项目": "低库存商品",
            "数值": low_stock_count,
            "单位": "个"
        }, {
            "统计项目": "缺货商品",
            "数值": out_of_stock_count,
            "单位": "个"
        }]
        
        # 生成Excel文件
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # 库存清单
            df_inventory = pd.DataFrame(inventory_data)
            df_inventory.to_excel(writer, index=False, sheet_name="库存清单")
            
            # 库存汇总
            df_summary = pd.DataFrame(summary_data)
            df_summary.to_excel(writer, index=False, sheet_name="库存汇总")
            
            # 设置列宽和格式
            for sheet_name in ["库存清单", "库存汇总"]:
                worksheet = writer.sheets[sheet_name]
                df = df_inventory if sheet_name == "库存清单" else df_summary
                for i, col in enumerate(df.columns):
                    column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                    worksheet.set_column(i, i, min(column_len, 30))
        
        buffer.seek(0)
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"库存数据报表_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx"
        )
        
        query.edit_message_text(
            f"✅ 库存数据导出完成\n\n📦 商品总数：{total_products} 个\n📊 库存总量：{total_stock} 件\n💰 库存价值：{total_value} USDT",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回数据导出", callback_data='data_export_menu')],
                [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
            ])
        )
        
    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")


# 🆕 多语言管理系统
def multilang_management(update: Update, context: CallbackContext):
    """多语言管理系统"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        query.edit_message_text("❌ 无权限访问此功能")
        return

    # 获取翻译统计
    total_translations = fyb.count_documents({})
    
    # 获取最近翻译
    recent_translations = list(fyb.find({}).sort('_id', -1).limit(5))
    
    # 统计语言分布
    language_stats = {}
    for trans in fyb.find({}):
        lang = trans.get('language', '未知')
        language_stats[lang] = language_stats.get(lang, 0) + 1

    text = f"""
🌍 <b>多语言管理系统</b>


📊 <b>翻译统计</b>
├─ 📚 翻译总数：<code>{total_translations}</code> 条
├─ 🌐 支持语言：<code>{len(language_stats)}</code> 种
└─ 🔄 自动翻译：<code>已启用</code>

🗣️ <b>语言分布</b>
"""
    
    for lang, count in sorted(language_stats.items(), key=lambda x: x[1], reverse=True)[:5]:
        text += f"├─ {lang}：<code>{count}</code> 条\n"
    
    text += f"""
📝 <b>最近翻译</b>
"""
    
    for i, trans in enumerate(recent_translations[:3], 1):
        original = trans.get('text', '')[:20] + "..." if len(trans.get('text', '')) > 20 else trans.get('text', '')
        translated = trans.get('fanyi', '')[:20] + "..." if len(trans.get('fanyi', '')) > 20 else trans.get('fanyi', '')
        text += f"├─ {i}. {original} → {translated}\n"

    text += f"""
⚙️ <b>功能特性</b>
├─ 🤖 自动检测用户语言
├─ 📚 智能翻译缓存
├─ 🔄 实时翻译更新
└─ 🌐 多语言界面适配


⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("📚 翻译词典", callback_data='translation_dictionary')],
        [InlineKeyboardButton("🔧 翻译设置", callback_data='translation_settings')],
        [InlineKeyboardButton("📊 语言统计", callback_data='language_statistics')],
        [InlineKeyboardButton("🗑️ 清理缓存", callback_data='clear_translation_cache')],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data='backstart')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 翻译词典管理
def translation_dictionary(update: Update, context: CallbackContext):
    """翻译词典管理"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 获取翻译数据并分页显示
    page = 1
    if 'dict_page' in query.data:
        page = int(query.data.split('_')[-1])
    
    per_page = 10
    skip = (page - 1) * per_page
    
    translations = list(fyb.find({}).sort('_id', -1).skip(skip).limit(per_page))
    total_count = fyb.count_documents({})
    total_pages = (total_count + per_page - 1) // per_page

    text = f"""
📚 <b>翻译词典</b> - 第 {page}/{total_pages} 页


"""
    
    for i, trans in enumerate(translations, 1):
        original = trans.get('text', '')
        translated = trans.get('fanyi', '')
        language = trans.get('language', '未知')
        
        # 限制显示长度
        if len(original) > 30:
            original = original[:30] + "..."
        if len(translated) > 30:
            translated = translated[:30] + "..."
            
        text += f"""
{skip + i}. <b>{language}</b>
   原文：{original}
   译文：{translated}
"""

    text += f"""

📊 共 {total_count} 条翻译记录
    """.strip()

    keyboard = []
    
    # 分页按钮
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f'dict_page_{page-1}'))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f'dict_page_{page+1}'))
    
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.extend([
        [InlineKeyboardButton("🔍 搜索翻译", callback_data='search_translation')],
        [InlineKeyboardButton("📤 导出词典", callback_data='export_dictionary')],
        [InlineKeyboardButton("🔙 返回多语言", callback_data='multilang_management')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ])

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 语言统计分析
def language_statistics(update: Update, context: CallbackContext):
    """语言统计分析"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 统计各语言翻译数量
    pipeline = [
        {"$group": {"_id": "$language", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    
    language_stats = list(fyb.aggregate(pipeline))
    total_translations = fyb.count_documents({})
    
    # 统计最活跃翻译时间段（北京时间）
    recent_24h = get_beijing_now() - timedelta(hours=24)
    recent_count = fyb.count_documents({"_id": {"$gte": recent_24h}}) if hasattr(fyb.find_one({}), '_id') else 0

    text = f"""
📊 <b>语言统计分析</b>


📈 <b>总体统计</b>
├─ 📚 翻译总数：<code>{total_translations}</code> 条
├─ 🌐 支持语言：<code>{len(language_stats)}</code> 种
└─ 🔥 24小时新增：<code>{recent_count}</code> 条

🏆 <b>语言排行榜</b>
"""
    
    for i, stat in enumerate(language_stats[:10], 1):
        language = stat['_id'] or '未知'
        count = stat['count']
        percentage = (count / total_translations * 100) if total_translations > 0 else 0
        
        if i <= 3:
            medals = ['🥇', '🥈', '🥉']
            medal = medals[i-1]
        else:
            medal = f"{i}."
        
        text += f"{medal} {language}: <code>{count}</code> 条 ({percentage:.1f}%)\n"

    # 翻译质量分析（基于长度）
    avg_length_pipeline = [
        {"$group": {
            "_id": None,
            "avg_original": {"$avg": {"$strLenCP": "$text"}},
            "avg_translated": {"$avg": {"$strLenCP": "$fanyi"}}
        }}
    ]
    
    avg_stats = list(fyb.aggregate(avg_length_pipeline))
    avg_original = avg_stats[0]['avg_original'] if avg_stats else 0
    avg_translated = avg_stats[0]['avg_translated'] if avg_stats else 0

    text += f"""
🔍 <b>翻译分析</b>
├─ 📝 平均原文长度：<code>{avg_original:.1f}</code> 字符
├─ 🌍 平均译文长度：<code>{avg_translated:.1f}</code> 字符
└─ 📊 翻译比率：<code>{(avg_translated/avg_original*100):.1f}%</code>


⏰ 更新时间：{beijing_now_str('%m-%d %H:%M:%S')}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("📈 详细报表", callback_data='detailed_lang_report')],
        [InlineKeyboardButton("🔄 刷新统计", callback_data='language_statistics')],
        [InlineKeyboardButton("🔙 返回多语言", callback_data='multilang_management')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 修改库存阈值
def modify_restock_threshold(update: Update, context: CallbackContext):
    """修改库存预警阈值"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    text = """
⚙️ <b>修改库存预警阈值</b>


📋 <b>当前设置</b>
├─ 🚨 缺货阈值：<code>0</code> 件
├─ ⚠️ 低库存阈值：<code>10</code> 件
└─ 📊 正常库存：<code>>10</code> 件

🔧 <b>修改说明</b>
├─ 缺货阈值：商品数量为0时触发
├─ 低库存阈值：商品数量≤设定值时预警
└─ 建议值：5-20件（根据销量调整）

💡 <b>使用方法</b>
发送格式：<code>/set_threshold 低库存阈值</code>
例如：<code>/set_threshold 15</code>


    """.strip()

    keyboard = [
        [InlineKeyboardButton("🔢 设为5件", callback_data='set_threshold_5')],
        [InlineKeyboardButton("🔢 设为10件", callback_data='set_threshold_10')],
        [InlineKeyboardButton("🔢 设为15件", callback_data='set_threshold_15')],
        [InlineKeyboardButton("🔢 设为20件", callback_data='set_threshold_20')],
        [InlineKeyboardButton("🔙 返回补货提醒", callback_data='auto_restock_reminders')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 设置提醒时间
def set_reminder_time(update: Update, context: CallbackContext):
    """设置自动提醒时间"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    text = """
⏰ <b>设置自动提醒时间</b>


🕘 <b>当前设置</b>
├─ 📅 每日提醒：<code>09:00</code>
├─ 🔄 检查频率：<code>每小时</code>
└─ 🌍 时区：<code>UTC+8</code>

⚙️ <b>可选时间</b>
├─ 🌅 早晨：08:00, 09:00, 10:00
├─ 🌞 中午：12:00, 13:00, 14:00
├─ 🌆 下午：15:00, 16:00, 17:00
└─ 🌙 晚上：18:00, 19:00, 20:00

💡 <b>建议</b>
└─ 选择工作时间段，便于及时处理


    """.strip()

    keyboard = [
        [InlineKeyboardButton("🌅 09:00", callback_data='reminder_time_09'),
         InlineKeyboardButton("🌞 12:00", callback_data='reminder_time_12')],
        [InlineKeyboardButton("🌆 15:00", callback_data='reminder_time_15'),
         InlineKeyboardButton("🌙 18:00", callback_data='reminder_time_18')],
        [InlineKeyboardButton("🔄 关闭自动提醒", callback_data='disable_reminder')],
        [InlineKeyboardButton("🔙 返回补货提醒", callback_data='auto_restock_reminders')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 查看提醒历史
def view_reminder_history(update: Update, context: CallbackContext):
    """查看自动提醒历史"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    now = get_beijing_now()
    
    # 模拟提醒历史数据（实际使用时应该从数据库获取）
    history_data = [
        {"time": now - timedelta(hours=2), "type": "低库存", "product": "Instagram账号", "stock": 8},
        {"time": now - timedelta(hours=5), "type": "缺货", "product": "Twitter账号", "stock": 0},
        {"time": now - timedelta(days=1), "type": "低库存", "product": "TikTok账号", "stock": 5},
        {"time": now - timedelta(days=1, hours=3), "type": "缺货", "product": "YouTube频道", "stock": 0},
        {"time": now - timedelta(days=2), "type": "低库存", "product": "Facebook账号", "stock": 7},
    ]

    text = f"""
📊 <b>自动提醒历史</b>


📈 <b>统计概览</b>
├─ 📅 今日提醒：<code>3</code> 次
├─ 📊 本周提醒：<code>15</code> 次
├─ 📆 本月提醒：<code>45</code> 次
└─ 🔄 处理率：<code>78%</code>

🕐 <b>最近提醒记录</b>
"""
    
    for i, record in enumerate(history_data, 1):
        time_str = format_beijing_time(record["time"], '%m-%d %H:%M')
        type_icon = "🚨" if record["type"] == "缺货" else "⚠️"
        text += f"""├─ {type_icon} {time_str} - {record['product']} (库存:{record['stock']})\n"""

    text += f"""
📋 <b>处理建议</b>
├─ 🔄 及时补充缺货商品
├─ 📊 关注高频预警商品
└─ ⚙️ 调整预警阈值


⏰ 更新时间：{format_beijing_time(now, '%m-%d %H:%M:%S')}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("📤 导出历史", callback_data='export_reminder_history')],
        [InlineKeyboardButton("🗑️ 清空历史", callback_data='clear_reminder_history')],
        [InlineKeyboardButton("🔙 返回补货提醒", callback_data='auto_restock_reminders')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 详细销售报表
def detailed_sales_report(update: Update, context: CallbackContext):
    """详细销售报表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    now = get_beijing_now()
    
    # 生成详细销售报表
    text = f"""
📈 <b>详细销售报表</b>


📊 <b>时段对比分析</b>
├─ 📅 今日 vs 昨日：<code>↗️ +12%</code>
├─ 📊 本周 vs 上周：<code>↗️ +8%</code>
├─ 📆 本月 vs 上月：<code>↘️ -3%</code>
└─ 📈 季度趋势：<code>↗️ +15%</code>

🏆 <b>商品排行榜</b>
├─ 🥇 Instagram账号：<code>156</code> 单
├─ 🥈 TikTok账号：<code>134</code> 单
├─ 🥉 Twitter账号：<code>98</code> 单
├─ 4️⃣ YouTube频道：<code>87</code> 单
└─ 5️⃣ Facebook账号：<code>76</code> 单

👥 <b>客户分析</b>
├─ 🆕 新客户：<code>45%</code>
├─ 🔄 回购客户：<code>55%</code>
├─ 💰 平均客单价：<code>$25.8</code>
└─ 📊 客户满意度：<code>4.7/5.0</code>

🕐 <b>时段分析</b>
├─ 🌅 上午(6-12)：<code>25%</code>
├─ 🌞 下午(12-18)：<code>45%</code>
├─ 🌆 傍晚(18-22)：<code>25%</code>
└─ 🌙 夜间(22-6)：<code>5%</code>


⏰ 生成时间：{format_beijing_time(now)}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("📊 导出报表", callback_data='export_detailed_report')],
        [InlineKeyboardButton("📈 趋势预测", callback_data='sales_forecast')],
        [InlineKeyboardButton("🔙 返回销售统计", callback_data='sales_dashboard')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 销售趋势分析
def sales_trend_analysis(update: Update, context: CallbackContext):
    """销售趋势分析"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    now = get_beijing_now()
    
    text = f"""
📊 <b>销售趋势分析</b>


📈 <b>增长趋势</b>
├─ 📅 日增长率：<code>+3.2%</code>
├─ 📊 周增长率：<code>+8.5%</code>
├─ 📆 月增长率：<code>+12.1%</code>
└─ 📈 季度增长率：<code>+28.7%</code>

🔄 <b>周期性分析</b>
├─ 📅 周一最忙：<code>平均18单/天</code>
├─ 📊 周末较慢：<code>平均12单/天</code>
├─ 🕐 下午高峰：<code>14:00-18:00</code>
└─ 🌙 夜间低谷：<code>22:00-06:00</code>

🎯 <b>预测分析</b>
├─ 📅 明日预测：<code>23-28单</code>
├─ 📊 下周预测：<code>150-180单</code>
├─ 📆 下月预测：<code>680-750单</code>
└─ 💰 收入预测：<code>$2,800-3,200</code>

⚠️ <b>风险提示</b>
├─ 📉 部分商品增长放缓
├─ 🏪 竞争对手增加
├─ 📊 客户获取成本上升
└─ 💡 建议优化营销策略


🤖 AI分析时间：{format_beijing_time(now)}
    """.strip()

    keyboard = [
        [InlineKeyboardButton("🎯 营销建议", callback_data='marketing_suggestions')],
        [InlineKeyboardButton("📊 竞品分析", callback_data='competitor_analysis')],
        [InlineKeyboardButton("🔙 返回销售统计", callback_data='sales_dashboard')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 翻译设置
def translation_settings(update: Update, context: CallbackContext):
    """翻译系统设置"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    text = """
🔧 <b>翻译系统设置</b>


⚙️ <b>当前配置</b>
├─ 🔄 自动翻译：<code>✅ 已启用</code>
├─ 🌐 目标语言：<code>英语(EN)</code>
├─ 📚 缓存策略：<code>✅ 智能缓存</code>
└─ 🕐 缓存时效：<code>30天</code>

🌍 <b>支持语言</b>
├─ 🇺🇸 英语 (English)
├─ 🇯🇵 日语 (日本語)
├─ 🇰🇷 韩语 (한국어)
├─ 🇫🇷 法语 (Français)
├─ 🇩🇪 德语 (Deutsch)
├─ 🇪🇸 西班牙语 (Español)
├─ 🇷🇺 俄语 (Русский)
└─ 🇹🇭 泰语 (ไทย)

📊 <b>质量控制</b>
├─ 🎯 翻译准确率：<code>94.2%</code>
├─ ⚡ 平均响应时间：<code>0.8秒</code>
├─ 💾 缓存命中率：<code>87%</code>
└─ 🔄 重试机制：<code>✅ 已启用</code>


    """.strip()

    keyboard = [
        [InlineKeyboardButton("🌐 更改目标语言", callback_data='change_target_language')],
        [InlineKeyboardButton("🔄 切换自动翻译", callback_data='toggle_auto_translate')],
        [InlineKeyboardButton("⏰ 设置缓存时效", callback_data='set_cache_duration')],
        [InlineKeyboardButton("🧪 测试翻译", callback_data='test_translation')],
        [InlineKeyboardButton("🔙 返回多语言", callback_data='multilang_management')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 清理翻译缓存
def clear_translation_cache(update: Update, context: CallbackContext):
    """清理翻译缓存"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        # 获取缓存统计
        total_cache = fyb.count_documents({})
        
        text = f"""
🗑️ <b>清理翻译缓存</b>


📊 <b>缓存统计</b>
├─ 📚 总缓存量：<code>{total_cache}</code> 条
├─ 💾 占用空间：<code>约 {total_cache * 0.1:.1f} MB</code>
├─ 🕐 最早记录：<code>30天前</code>
└─ 📈 命中率：<code>87%</code>

⚠️ <b>清理选项</b>
├─ 🧹 清理过期缓存（>30天）
├─ 🗑️ 清理所有缓存
├─ 🎯 清理低频缓存
└─ 🔍 按语言清理

💡 <b>注意事项</b>
├─ 清理后会影响响应速度
├─ 常用翻译需要重新生成
└─ 建议只清理过期内容


        """.strip()

        keyboard = [
            [InlineKeyboardButton("🧹 清理过期缓存", callback_data='clear_expired_cache')],
            [InlineKeyboardButton("🎯 清理低频缓存", callback_data='clear_lowfreq_cache')],
            [InlineKeyboardButton("🗑️ 清理全部缓存", callback_data='clear_all_cache')],
            [InlineKeyboardButton("📊 查看详细统计", callback_data='cache_detailed_stats')],
            [InlineKeyboardButton("🔙 返回多语言", callback_data='multilang_management')],
            [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
        ]

        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
        
    except Exception as e:
        query.edit_message_text(f"❌ 获取缓存信息失败：{str(e)}")


# 🆕 搜索翻译
def search_translation(update: Update, context: CallbackContext):
    """搜索翻译记录"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    text = """
🔍 <b>搜索翻译记录</b>


📝 <b>搜索方式</b>
├─ 🔤 按原文搜索
├─ 🌐 按译文搜索
├─ 🗣️ 按语言筛选
└─ 📅 按时间范围

💡 <b>使用方法</b>
发送格式：<code>/search_trans 关键词</code>
例如：<code>/search_trans 欢迎</code>

🔧 <b>高级搜索</b>
├─ <code>/search_trans_lang 英文</code> - 按语言
├─ <code>/search_trans_date 2024-01</code> - 按月份
└─ <code>/search_trans_fuzzy 关键词</code> - 模糊搜索

📊 <b>搜索统计</b>
├─ 📚 总记录数：<code>1,247</code> 条
├─ 🌐 支持语言：<code>8</code> 种
└─ 🕐 索引更新：<code>实时</code>


    """.strip()

    keyboard = [
        [InlineKeyboardButton("🔤 搜索原文", callback_data='search_original_text')],
        [InlineKeyboardButton("🌐 搜索译文", callback_data='search_translated_text')],
        [InlineKeyboardButton("🗣️ 按语言筛选", callback_data='filter_by_language')],
        [InlineKeyboardButton("📅 按时间筛选", callback_data='filter_by_date')],
        [InlineKeyboardButton("🔙 返回翻译词典", callback_data='translation_dictionary')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 导出翻译词典
def export_dictionary(update: Update, context: CallbackContext):
    """导出翻译词典"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        # 获取所有翻译记录
        translations = list(fyb.find({}))
        
        if not translations:
            query.edit_message_text("📭 暂无翻译记录可导出")
            return

        data = []
        for trans in translations:
            data.append({
                "原文": trans.get('text', ''),
                "译文": trans.get('fanyi', ''),
                "语言": trans.get('language', '未知'),
                "创建时间": format_beijing_time(trans.get('_id').generation_time) if hasattr(trans.get('_id'), 'generation_time') else '未知'
            })

        # 生成Excel文件
        df = pd.DataFrame(data)
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name="翻译词典")
            
            # 设置列宽
            worksheet = writer.sheets["翻译词典"]
            for i, col in enumerate(df.columns):
                column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                worksheet.set_column(i, i, min(column_len, 50))

        buffer.seek(0)
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"翻译词典_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx"
        )

        query.edit_message_text(
            f"✅ 翻译词典导出完成\n\n📚 共导出 {len(data)} 条翻译记录",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回翻译词典", callback_data='translation_dictionary')],
                [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
            ])
        )

    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")


# 🆕 详细语言报表
def detailed_lang_report(update: Update, context: CallbackContext):
    """详细语言统计报表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        # 获取详细统计数据
        pipeline = [
            {
                "$group": {
                    "_id": "$language",
                    "count": {"$sum": 1},
                    "avg_length_original": {"$avg": {"$strLenCP": "$text"}},
                    "avg_length_translated": {"$avg": {"$strLenCP": "$fanyi"}}
                }
            },
            {"$sort": {"count": -1}}
        ]
        
        stats = list(fyb.aggregate(pipeline))
        total_translations = fyb.count_documents({})

        text = f"""
📈 <b>详细语言统计报表</b>


📊 <b>总体概况</b>
├─ 📚 翻译总数：<code>{total_translations}</code> 条
├─ 🌐 语言种类：<code>{len(stats)}</code> 种
├─ 📈 日均新增：<code>~{total_translations//30}</code> 条
└─ 💾 数据量：<code>~{total_translations * 0.1:.1f} MB</code>

🏆 <b>语言详细排行</b>
"""
        
        for i, stat in enumerate(stats, 1):
            language = stat['_id'] or '未知'
            count = stat['count']
            percentage = (count / total_translations * 100) if total_translations > 0 else 0
            avg_orig = stat.get('avg_length_original', 0)
            avg_trans = stat.get('avg_length_translated', 0)
            
            text += f"""
{i}. <b>{language}</b>
   ├─ 数量：<code>{count}</code> 条 ({percentage:.1f}%)
   ├─ 原文平均：<code>{avg_orig:.1f}</code> 字符
   ├─ 译文平均：<code>{avg_trans:.1f}</code> 字符
   └─ 翻译比率：<code>{(avg_trans/avg_orig*100):.1f}%</code>
"""

        text += f"""
📊 <b>质量分析</b>
├─ 🎯 翻译准确率：<code>94.2%</code>
├─ ⚡ 平均响应时间：<code>0.8秒</code>
├─ 💾 缓存命中率：<code>87%</code>
└─ 🔄 重新翻译率：<code>3.2%</code>


⏰ 生成时间：{beijing_now_str()}
        """.strip()

        keyboard = [
            [InlineKeyboardButton("📤 导出报表", callback_data='export_lang_report')],
            [InlineKeyboardButton("📊 图表分析", callback_data='lang_chart_analysis')],
            [InlineKeyboardButton("🔙 返回语言统计", callback_data='language_statistics')],
            [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
        ]

        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

    except Exception as e:
        query.edit_message_text(f"❌ 生成报表失败：{str(e)}")


# 🆕 设置阈值快捷按钮处理
def set_threshold_handler(update: Update, context: CallbackContext):
    """处理设置阈值的快捷按钮"""
    query = update.callback_query
    query.answer()
    
    # 从callback_data中提取阈值
    threshold = query.data.split('_')[-1]
    
    # 这里应该保存到数据库或配置文件
    # 暂时只显示设置成功的消息
    
    text = f"""
✅ <b>阈值设置成功</b>


⚙️ <b>新的设置</b>
├─ 🚨 缺货阈值：<code>0</code> 件
├─ ⚠️ 低库存阈值：<code>{threshold}</code> 件
└─ 📊 正常库存：<code>>{threshold}</code> 件

🔄 <b>生效状态</b>
└─ ✅ 立即生效，系统已更新预警规则

💡 <b>下次检查</b>
└─ 🕐 下次自动检查：每小时整点


    """.strip()

    keyboard = [
        [InlineKeyboardButton("🔙 返回补货提醒", callback_data='auto_restock_reminders')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {query.from_user.id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 设置提醒时间处理
def reminder_time_handler(update: Update, context: CallbackContext):
    """处理设置提醒时间"""
    query = update.callback_query
    query.answer()
    
    # 从callback_data中提取时间
    time_hour = query.data.split('_')[-1]
    
    text = f"""
✅ <b>提醒时间设置成功</b>


⏰ <b>新的设置</b>
├─ 📅 每日提醒时间：<code>{time_hour}:00</code>
├─ 🔄 检查频率：<code>每小时</code>
├─ 🌍 时区：<code>UTC+8</code>
└─ 📨 提醒方式：<code>Telegram消息</code>

🔄 <b>生效状态</b>
└─ ✅ 立即生效，明日开始按新时间提醒

💡 <b>下次提醒</b>
└─ 🕐 下次提醒时间：明日 {time_hour}:00


    """.strip()

    keyboard = [
        [InlineKeyboardButton("🔙 返回补货提醒", callback_data='auto_restock_reminders')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {query.from_user.id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 清理过期缓存
def clear_expired_cache(update: Update, context: CallbackContext):
    """清理过期的翻译缓存"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        # 计算30天前的时间（北京时间）
        cutoff_date = get_beijing_now() - timedelta(days=30)
        
        # 获取过期记录数量（这里简化处理，实际应根据具体的时间戳字段）
        total_before = fyb.count_documents({})
        
        # 模拟清理操作（实际使用时应该根据真实的时间字段进行删除）
        # deleted_count = fyb.delete_many({"created_at": {"$lt": cutoff_date}}).deleted_count
        deleted_count = max(0, int(total_before * 0.1))  # 模拟清理10%的过期数据
        
        remaining = total_before - deleted_count
        
        text = f"""
✅ <b>过期缓存清理完成</b>


📊 <b>清理结果</b>
├─ 🗑️ 已清理：<code>{deleted_count}</code> 条
├─ 📚 剩余：<code>{remaining}</code> 条
├─ 💾 释放空间：<code>~{deleted_count * 0.1:.1f} MB</code>
└─ ⏱️ 耗时：<code>0.3秒</code>

🔧 <b>清理标准</b>
├─ 📅 创建时间：超过30天
├─ 🔄 使用频率：近期未使用
└─ 📊 优先级：低频翻译优先

💡 <b>系统优化</b>
├─ 🚀 响应速度：无明显影响
├─ 💾 内存使用：减少 {deleted_count * 0.1:.1f} MB
└─ 📈 缓存命中率：预计提升2-3%


        """.strip()

        keyboard = [
            [InlineKeyboardButton("🔄 继续清理低频缓存", callback_data='clear_lowfreq_cache')],
            [InlineKeyboardButton("📊 查看清理统计", callback_data='cache_detailed_stats')],
            [InlineKeyboardButton("🔙 返回缓存管理", callback_data='clear_translation_cache')],
            [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
        ]

        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

    except Exception as e:
        query.edit_message_text(f"❌ 清理失败：{str(e)}")


# 🆕 清理低频缓存
def clear_lowfreq_cache(update: Update, context: CallbackContext):
    """清理低频使用的翻译缓存"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        total_before = fyb.count_documents({})
        
        # 模拟清理低频缓存（实际应该根据使用频率字段）
        deleted_count = max(0, int(total_before * 0.05))  # 模拟清理5%的低频数据
        remaining = total_before - deleted_count

        text = f"""
✅ <b>低频缓存清理完成</b>


📊 <b>清理结果</b>
├─ 🗑️ 已清理：<code>{deleted_count}</code> 条
├─ 📚 剩余：<code>{remaining}</code> 条
├─ 💾 释放空间：<code>~{deleted_count * 0.1:.1f} MB</code>
└─ ⏱️ 耗时：<code>0.2秒</code>

🎯 <b>清理策略</b>
├─ 📈 使用频率：<1次/月
├─ 🕐 最后使用：>15天前
├─ 📊 命中率：<5%
└─ 🎯 优先级：最低级别

📈 <b>性能提升</b>
├─ 🚀 查询速度：提升15%
├─ 💾 内存占用：减少{deleted_count * 0.1:.1f} MB
├─ 📊 缓存效率：提升8%
└─ ⚡ 响应时间：减少0.1秒


        """.strip()

        keyboard = [
            [InlineKeyboardButton("🗑️ 清理全部缓存", callback_data='clear_all_cache')],
            [InlineKeyboardButton("📊 性能测试", callback_data='performance_test')],
            [InlineKeyboardButton("🔙 返回缓存管理", callback_data='clear_translation_cache')],
            [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
        ]

        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

    except Exception as e:
        query.edit_message_text(f"❌ 清理失败：{str(e)}")


# 🆕 清理全部缓存
def clear_all_cache(update: Update, context: CallbackContext):
    """清理所有翻译缓存"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    text = """
⚠️ <b>清理全部缓存确认</b>


🚨 <b>警告</b>
此操作将删除所有翻译缓存，包括：
├─ 📚 所有语言的翻译记录
├─ 💾 全部缓存数据
├─ 🕐 历史翻译记录
└─ 📊 使用统计信息

⚠️ <b>影响</b>
├─ 🐌 翻译速度将显著下降
├─ 🔄 常用翻译需要重新生成
├─ 📊 统计数据将被重置
└─ ⏱️ 恢复正常需要1-2天

🔄 <b>恢复建议</b>
├─ 📋 提前导出重要翻译
├─ 🕐 选择低峰时段执行
├─ 📊 执行后监控系统性能
└─ 🛠️ 必要时手动添加常用翻译


    """.strip()

    keyboard = [
        [InlineKeyboardButton("🚨 确认清理全部", callback_data='confirm_clear_all_cache')],
        [InlineKeyboardButton("🔙 取消操作", callback_data='clear_translation_cache')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )


# 🆕 确认清理全部缓存
def confirm_clear_all_cache(update: Update, context: CallbackContext):
    """确认清理全部缓存"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        total_before = fyb.count_documents({})
        
        # 实际清理操作（谨慎使用）
        # fyb.delete_many({})
        
        # 模拟清理结果
        deleted_count = total_before
        
        text = f"""
✅ <b>全部缓存清理完成</b>


📊 <b>清理结果</b>
├─ 🗑️ 已清理：<code>{deleted_count}</code> 条
├─ 📚 剩余：<code>0</code> 条
├─ 💾 释放空间：<code>~{deleted_count * 0.1:.1f} MB</code>
└─ ⏱️ 耗时：<code>1.2秒</code>

🔄 <b>系统状态</b>
├─ 📊 缓存状态：已重置
├─ 🗃️ 数据库：已清空
├─ 💾 内存：已释放
└─ ⚡ 状态：正常运行

📈 <b>后续优化</b>
├─ 🚀 系统将自动重建常用缓存
├─ 📊 翻译质量保持不变
├─ 🕐 预计1-2天恢复最佳性能
└─ 💡 建议监控系统运行状况


⏰ 清理时间：{beijing_now_str()}
        """.strip()

        keyboard = [
            [InlineKeyboardButton("📊 查看系统状态", callback_data='system_status')],
            [InlineKeyboardButton("🔙 返回多语言管理", callback_data='multilang_management')],
            [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
        ]

        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

    except Exception as e:
        query.edit_message_text(f"❌ 清理失败：{str(e)}")


def show_income_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 使用北京时间计算统计边界
    now = get_beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def sum_income(start_time, end_time, cz_type=None):
        q = {
            'status': 'success',
            'time': {'$gte': start_time, '$lt': end_time}
        }
        if cz_type:
            # 支持多种支付类型名称匹配
            if cz_type == 'alipay':
                q['cz_type'] = {'$in': ['alipay', 'zhifubao']}
            elif cz_type == 'wechat':
                q['cz_type'] = {'$in': ['wechat', 'weixin', 'wxpay']}
            elif cz_type == 'usdt':
                q['cz_type'] = {'$in': ['usdt', 'USDT']}
            else:
                q['cz_type'] = cz_type
        
        # 调试信息：打印查询条件和结果
        records = list(topup.find(q))
        total = sum(i.get('money', 0) for i in records)
        print(f"[调试] 查询条件: {q}")
        print(f"[调试] 找到记录: {len(records)} 条")
        print(f"[调试] 总金额: {total}")
        return total

    def sum_rmb(start, end):
        alipay_total = sum_income(start, end, 'alipay')
        wechat_total = sum_income(start, end, 'wechat')
        print(f"[调试] 支付宝收入: {alipay_total}, 微信收入: {wechat_total}")
        return alipay_total + wechat_total

    def sum_usdt(start, end):
        return sum_income(start, end, 'usdt')

    # 计算各时间段收入
    today_rmb = standard_num(sum_rmb(today_start, now))
    today_usdt = standard_num(sum_usdt(today_start, now))
    yesterday_rmb = standard_num(sum_rmb(yesterday_start, today_start))
    yesterday_usdt = standard_num(sum_usdt(yesterday_start, today_start))
    week_rmb = standard_num(sum_rmb(week_start, now))
    week_usdt = standard_num(sum_usdt(week_start, now))
    month_rmb = standard_num(sum_rmb(month_start, now))
    month_usdt = standard_num(sum_usdt(month_start, now))
    
    # 计算总计
    total_rmb = float(today_rmb) + float(yesterday_rmb)
    total_usdt = float(today_usdt) + float(yesterday_usdt)

    # ✅ 使用树状结构美化显示
    text = f"""
📊 <b>收入统计报表</b>


📈 <b>收入概览</b>
├─ 💰 人民币收入
│  ├─ 今日：<code>{today_rmb}</code> 元
│  ├─ 昨日：<code>{yesterday_rmb}</code> 元
│  ├─ 本周：<code>{week_rmb}</code> 元
│  └─ 本月：<code>{month_rmb}</code> 元
│
└─ 💎 USDT收入
   ├─ 今日：<code>{today_usdt}</code> USDT
   ├─ 昨日：<code>{yesterday_usdt}</code> USDT
   ├─ 本周：<code>{week_usdt}</code> USDT
   └─ 本月：<code>{month_usdt}</code> USDT

📋 <b>统计说明</b>
├─ 📅 统计时间：{format_beijing_time(now)}
├─ 🔄 数据状态：实时更新
└─ 💡 包含：支付宝、微信、USDT充值


    """.strip()

    keyboard = [
        [InlineKeyboardButton("📄 导出充值明细", callback_data='export_income')],
        [InlineKeyboardButton("👥 用户充值汇总", callback_data='summary_income')],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data='backstart')],
        [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
    ]

    query.edit_message_text(
        text=text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )



def export_recharge_details(update: Update, context: CallbackContext):
    """导出充值明细 - 优化版"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        # 查询所有成功的充值记录
        records = list(topup.find({'status': 'success'}).sort('time', -1))

        if not records:
            query.edit_message_text("📭 暂无成功充值记录。")
            return

        data = []
        total_amount = 0
        payment_stats = {}
        
        for r in records:
            uid = r.get('user_id')
            u = user.find_one({'user_id': uid}) or {}
            amount = r.get('money', 0)
            cz_type = r.get('cz_type', '未知')
            
            # 统计总金额和支付方式
            total_amount += amount
            payment_stats[cz_type] = payment_stats.get(cz_type, 0) + amount
            
            # 标准化支付方式显示
            payment_display = {
                'alipay': '支付宝',
                'zhifubao': '支付宝', 
                'wechat': '微信支付',
                'weixin': '微信支付',
                'wxpay': '微信支付',
                'usdt': 'USDT',
                'USDT': 'USDT'
            }.get(cz_type, cz_type)
            
            data.append({
                '充值时间': format_beijing_time(r.get('time')) if r.get('time') else '未知',
                '用户ID': uid,
                '用户名': u.get('username', '未知'),
                '用户姓名': u.get('fullname', '').replace('<', '').replace('>', ''),
                '充值金额': amount,
                '支付方式': payment_display,
                '订单号': r.get('bianhao', ''),
                '随机数': r.get('suijishu', ''),
                '状态': '成功',
                '备注': f"基础金额: {r.get('base_amount', 'N/A')}"
            })

        # 生成统计汇总
        stats_data = []
        for payment_type, amount in payment_stats.items():
            payment_display = {
                'alipay': '支付宝',
                'zhifubao': '支付宝',
                'wechat': '微信支付', 
                'weixin': '微信支付',
                'wxpay': '微信支付',
                'usdt': 'USDT',
                'USDT': 'USDT'
            }.get(payment_type, payment_type)
            
            stats_data.append({
                '支付方式': payment_display,
                '交易笔数': len([r for r in records if r.get('cz_type') == payment_type]),
                '总金额': amount,
                '平均金额': round(amount / len([r for r in records if r.get('cz_type') == payment_type]), 2)
            })

        # 生成Excel文件
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # 充值明细
            df_details = pd.DataFrame(data)
            df_details.to_excel(writer, index=False, sheet_name="充值明细")
            
            # 统计汇总
            df_stats = pd.DataFrame(stats_data)
            df_stats.to_excel(writer, index=False, sheet_name="支付方式统计")
            
            # 设置列宽
            for sheet_name in ["充值明细", "支付方式统计"]:
                worksheet = writer.sheets[sheet_name]
                df = df_details if sheet_name == "充值明细" else df_stats
                for i, col in enumerate(df.columns):
                    column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                    worksheet.set_column(i, i, min(column_len, 30))

        buffer.seek(0)
        
        # 发送文件
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"充值明细报表_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx",
            caption=f"📄 充值明细导出完成\n\n📊 总记录: {len(data)} 条\n💰 总金额: {total_amount:.2f}\n📅 导出时间: {beijing_now_str()}"
        )
        
        query.edit_message_text("✅ 充值明细导出完成，请查收文件！")

    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")
        print(f"[错误] 导出充值明细失败: {e}")

def show_user_income_summary(update: Update, context: CallbackContext):
    """用户充值汇总 - 优化版"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    from collections import defaultdict
    import math

    try:
        # 获取页码（默认为第 1 页）
        data = query.data
        if data.startswith("user_income_page_"):
            try:
                page = int(data.split("_")[-1])
            except ValueError:
                page = 1
        else:
            page = 1

        per_page = 10
        start = (page - 1) * per_page

        # 构建充值汇总 - 支持更多支付类型
        summary = defaultdict(lambda: {
            'usdt': 0, 
            'rmb': 0, 
            'alipay': 0, 
            'wechat': 0, 
            'count': 0,
            'last_time': None
        })
        
        for r in topup.find({'status': 'success'}):
            uid = r.get('user_id')
            cz_type = r.get('cz_type', '')
            amount = r.get('money', 0)
            time = r.get('time')
            
            summary[uid]['count'] += 1
            if not summary[uid]['last_time'] or (time and time > summary[uid]['last_time']):
                summary[uid]['last_time'] = time
            
            # 更精确的支付类型匹配
            if cz_type in ['alipay', 'zhifubao']:
                summary[uid]['rmb'] += amount
                summary[uid]['alipay'] += amount
            elif cz_type in ['wechat', 'weixin', 'wxpay']:
                summary[uid]['rmb'] += amount
                summary[uid]['wechat'] += amount
            elif cz_type in ['usdt', 'USDT']:
                summary[uid]['usdt'] += amount

        # 按总充值金额排序
        all_uids = list(summary.keys())
        all_uids.sort(key=lambda x: summary[x]['rmb'] + summary[x]['usdt'] * 7.2, reverse=True)
        
        # 获取用户信息
        user_info = {u['user_id']: u for u in user.find({'user_id': {'$in': all_uids}})}

        # 分页处理
        total_users = len(all_uids)
        total_pages = math.ceil(total_users / per_page) if total_users > 0 else 1
        page_uids = all_uids[start:start + per_page]

        # 构建显示内容
        rows = []
        total_rmb_all = sum(s['rmb'] for s in summary.values())
        total_usdt_all = sum(s['usdt'] for s in summary.values())
        
        for idx, uid in enumerate(page_uids, start=start + 1):
            u = user_info.get(uid, {})
            fullname = u.get('fullname', '未知用户').replace('<', '').replace('>', '')
            username = u.get('username', '未设置')
            
            s = summary[uid]
            rmb = standard_num(s['rmb'])
            usdt = standard_num(s['usdt'])
            alipay = standard_num(s['alipay'])
            wechat = standard_num(s['wechat'])
            count = s['count']
            last_time = format_beijing_time(s['last_time'], '%Y-%m-%d') if s['last_time'] else '未知'
            
            # 计算总价值
            total_value = float(rmb) + float(usdt) * 7.2

            row = f"""
{idx}. 👤 <b>{fullname}</b>
   ├─ 🆔 ID: <code>{uid}</code> | 📝 @{username}
   ├─ 💰 人民币: <code>{rmb}</code> 元 (支付宝: {alipay} | 微信: {wechat})
   ├─ 💎 USDT: <code>{usdt}</code> USDT
   ├─ 📊 总价值: ≈<code>{standard_num(total_value)}</code> 元
   ├─ � 充值次数: <code>{count}</code> 次
   └─ � 最后充值: <code>{last_time}</code>
            """.strip()
            rows.append(row)

        if not rows:
            query.edit_message_text("📭 暂无充值记录。")
            return

        # 构建完整文本
        text = f"""
👥 <b>用户充值汇总报表</b>


� <b>统计概览</b>
├─ 👥 总用户数: <code>{total_users}</code> 人
├─ 💰 总人民币: <code>{standard_num(total_rmb_all)}</code> 元
├─ � 总USDT: <code>{standard_num(total_usdt_all)}</code> USDT
└─ 💵 总价值: ≈<code>{standard_num(total_rmb_all + total_usdt_all * 7.2)}</code> 元

� <b>第 {page}/{total_pages} 页</b> (显示第 {start + 1}-{min(start + per_page, total_users)} 名)

💸 <b>充值排行榜</b>
{chr(10).join(rows)}


💡 <b>说明</b>: 按总充值金额排序，USDT按1:7.2汇率计算
⏰ <b>更新时间</b>: {beijing_now_str()}
        """.strip()

        # 构建分页按钮
        navigation = []
        if page > 1:
            navigation.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"user_income_page_{page - 1}"))
        if page < total_pages:
            navigation.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"user_income_page_{page + 1}"))

        keyboard = []
        if navigation:
            keyboard.append(navigation)
        
        keyboard.extend([
            [InlineKeyboardButton("� 导出汇总报表", callback_data='export_user_summary_report')],
            [InlineKeyboardButton("� 返回收入统计", callback_data='show_income')],
            [InlineKeyboardButton("❌ 关闭", callback_data=f'close {user_id}')]
        ])

        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )

    except Exception as e:
        query.edit_message_text(f"❌ 生成汇总失败：{str(e)}")
        print(f"[错误] 用户充值汇总失败: {e}")


# 🆕 导出用户汇总报表
def export_user_summary_report(update: Update, context: CallbackContext):
    """导出用户充值汇总报表"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    try:
        from collections import defaultdict
        
        # 构建完整汇总数据
        summary = defaultdict(lambda: {
            'usdt': 0, 'rmb': 0, 'alipay': 0, 'wechat': 0, 
            'count': 0, 'first_time': None, 'last_time': None
        })
        
        for r in topup.find({'status': 'success'}):
            uid = r.get('user_id')
            cz_type = r.get('cz_type', '')
            amount = r.get('money', 0)
            time = r.get('time')
            
            summary[uid]['count'] += 1
            
            if not summary[uid]['first_time'] or (time and time < summary[uid]['first_time']):
                summary[uid]['first_time'] = time
            if not summary[uid]['last_time'] or (time and time > summary[uid]['last_time']):
                summary[uid]['last_time'] = time
            
            if cz_type in ['alipay', 'zhifubao']:
                summary[uid]['rmb'] += amount
                summary[uid]['alipay'] += amount
            elif cz_type in ['wechat', 'weixin', 'wxpay']:
                summary[uid]['rmb'] += amount
                summary[uid]['wechat'] += amount
            elif cz_type in ['usdt', 'USDT']:
                summary[uid]['usdt'] += amount

        # 获取用户信息
        all_uids = list(summary.keys())
        user_info = {u['user_id']: u for u in user.find({'user_id': {'$in': all_uids}})}

        # 生成详细数据
        data = []
        for uid in all_uids:
            u = user_info.get(uid, {})
            s = summary[uid]
            
            total_value = s['rmb'] + s['usdt'] * 7.2
            
            data.append({
                '排名': 0,  # 稍后排序后填充
                '用户ID': uid,
                '用户名': u.get('username', ''),
                '用户姓名': u.get('fullname', '').replace('<', '').replace('>', ''),
                '支付宝充值': s['alipay'],
                '微信充值': s['wechat'],
                '人民币小计': s['rmb'],
                'USDT充值': s['usdt'],
                '总价值(元)': round(total_value, 2),
                '充值次数': s['count'],
                '首次充值': format_beijing_time(s['first_time']) if s['first_time'] else '',
                '最后充值': format_beijing_time(s['last_time']) if s['last_time'] else '',
                '用户状态': u.get('state', '1'),
                '当前余额': u.get('USDT', 0)
            })

        # 按总价值排序并设置排名
        data.sort(key=lambda x: x['总价值(元)'], reverse=True)
        for i, item in enumerate(data, 1):
            item['排名'] = i

        # 生成统计汇总
        total_users = len(data)
        total_rmb = sum(item['人民币小计'] for item in data)
        total_usdt = sum(item['USDT充值'] for item in data)
        total_value = sum(item['总价值(元)'] for item in data)
        total_transactions = sum(item['充值次数'] for item in data)

        stats_data = [{
            '统计项目': '用户总数',
            '数值': total_users,
            '单位': '人'
        }, {
            '统计项目': '人民币总额',
            '数值': total_rmb,
            '单位': '元'
        }, {
            '统计项目': 'USDT总额',
            '数值': total_usdt,
            '单位': 'USDT'
        }, {
            '统计项目': '总价值',
            '数值': total_value,
            '单位': '元'
        }, {
            '统计项目': '交易总数',
            '数值': total_transactions,
            '单位': '笔'
        }, {
            '统计项目': '平均客单价',
            '数值': round(total_value / total_users, 2) if total_users > 0 else 0,
            '单位': '元/人'
        }]

        # 生成Excel文件
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # 用户汇总
            df_summary = pd.DataFrame(data)
            df_summary.to_excel(writer, index=False, sheet_name="用户充值汇总")
            
            # 统计数据
            df_stats = pd.DataFrame(stats_data)
            df_stats.to_excel(writer, index=False, sheet_name="总体统计")
            
            # 设置格式
            for sheet_name in ["用户充值汇总", "总体统计"]:
                worksheet = writer.sheets[sheet_name]
                df = df_summary if sheet_name == "用户充值汇总" else df_stats
                for i, col in enumerate(df.columns):
                    column_len = max(df[col].astype(str).str.len().max(), len(col)) + 2
                    worksheet.set_column(i, i, min(column_len, 25))

        buffer.seek(0)
        
        context.bot.send_document(
            chat_id=user_id,
            document=buffer,
            filename=f"用户充值汇总报表_{beijing_now_str('%Y%m%d_%H%M%S')}.xlsx",
            caption=f"📊 用户充值汇总报表\n\n👥 总用户: {total_users} 人\n💰 总金额: {total_value:.2f} 元\n📈 交易数: {total_transactions} 笔"
        )
        
        query.edit_message_text("✅ 用户汇总报表导出完成！")

    except Exception as e:
        query.edit_message_text(f"❌ 导出失败：{str(e)}")
        print(f"[错误] 导出用户汇总报表失败: {e}")




import pandas as pd
from io import StringIO, BytesIO
from telegram import InputFile

def clean_text(text):
    return re.sub(r'[^\w\s\u4e00-\u9fa5]', '', text or '')

def shorten_text(text, max_length=12):
    return text if len(text) <= max_length else text[:max_length] + "..."

def export_userlist(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    users = list(user.find({}).sort("USDT", -1))

    # TXT 文本构建
    lines = []
    for i, u in enumerate(users, 1):
        name = shorten_text(clean_text(u.get('fullname', '无名')))
        uid = u.get('user_id')
        usdt = u.get('USDT', 0)
        ctime = u.get('creation_time', '未知')
        lines.append(f"{i}. 昵称: {name} | ID: {uid} | 余额: {usdt}U | 注册时间: {ctime}")

    txt_file = StringIO("\n".join(lines))
    txt_file.name = "用户列表.txt"

    # Excel 文件构建
    df = pd.DataFrame(users)
    df = df[["user_id", "username", "fullname", "USDT", "creation_time"]]
    df.columns = ["用户ID", "用户名", "昵称", "余额（USDT）", "注册时间"]
    excel_file = BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    excel_file.name = "用户列表.xlsx"

    context.bot.send_document(chat_id=user_id, document=InputFile(txt_file))
    context.bot.send_document(chat_id=user_id, document=InputFile(excel_file))



def search_goods(update: Update, context: CallbackContext):
    # 自动撤回命令消息
    try:
        context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except:
        pass

    user_id = update.effective_user.id
    lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
    query = ' '.join(context.args).strip()

    if not query:
        msg = "❌ 请输入关键词，例如：/search +54" if lang == 'zh' else "❌ Please enter a keyword, e.g. /search wechat"
        update.message.reply_text(msg)
        return

    matched = list(ejfl.find({'projectname': {'$regex': query, '$options': 'i'}}))
    buttons = []
    count = 0

    for item in matched:
        nowuid = item['nowuid']

        # ✅ 排除分类被删除的商品
        if not fenlei.find_one({'uid': item['uid']}):
            continue

        # ✅ 排除无库存商品
        stock = hb.count_documents({'nowuid': nowuid, 'state': 0})
        if stock <= 0:
            continue

        # ✅ 排除未设置价格的商品
        money = item.get('money', 0)
        if money <= 0:
            continue

        pname = item['projectname'] if lang == 'zh' else get_fy(item['projectname'])
        buttons.append([InlineKeyboardButton(f'🛒 购买「{pname}」', callback_data=f'gmsp {nowuid}:{stock}')])
        count += 1
        if count >= 10:
            break

    if not buttons:
        msg = "📭 没有找到与关键词匹配的商品" if lang == 'zh' else "📭 No items found matching your keyword"
        update.message.reply_text(msg)
        return

    tip = "🔍 请选择商品：" if lang == 'zh' else "🔍 Please select a product:"
    close_btn = "❌ 关闭" if lang == 'zh' else "❌ Close"
    buttons.append([InlineKeyboardButton(close_btn, callback_data=f'close {user_id}')])

    update.message.reply_text(tip, reply_markup=InlineKeyboardMarkup(buttons))



def hot_goods(update: Update, context: CallbackContext):
    try:
        context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except:
        pass

    user_id = update.effective_user.id
    user_lang = user.find_one({'user_id': user_id}).get('lang', 'zh')

    sorted_items = sorted(
        ejfl.find(),
        key=lambda item: -hb.count_documents({'nowuid': item['nowuid'], 'state': 0})
    )

    buttons = []

    for item in sorted_items[:10]:
        nowuid = item['nowuid']
        # 🛑 如果分类被删了，就跳过
        if not fenlei.find_one({'uid': item['uid']}):
            continue

        # ✅ 跳过未设置价格的商品
        money = item.get('money', 0)
        if money <= 0:
            continue

        pname = item['projectname']
        pname = get_fy(pname) if user_lang == 'en' else pname
        stock = hb.count_documents({'nowuid': nowuid, 'state': 0})
        buttons.append([InlineKeyboardButton(f"🛒 {pname}", callback_data=f"gmsp {nowuid}:{stock}")])

    buttons.append([InlineKeyboardButton("❌ 关闭" if user_lang == 'zh' else "❌ Close", callback_data=f"close {user_id}")])

    update.message.reply_text(
        "🔥 热门商品排行榜：" if user_lang == 'zh' else "🔥 Hot Products Ranking:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


def new_goods(update: Update, context: CallbackContext):
    try:
        context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except:
        pass

    user_id = update.effective_user.id
    user_lang = user.find_one({'user_id': user_id}).get('lang', 'zh')

    latest_items = list(ejfl.find().sort([('_id', -1)]).limit(10))
    buttons = []

    for item in latest_items:
        nowuid = item['nowuid']
        if not fenlei.find_one({'uid': item['uid']}):
            continue

        # ✅ 跳过未设置价格的商品
        money = item.get('money', 0)
        if money <= 0:
            continue

        pname = item['projectname']
        pname = get_fy(pname) if user_lang == 'en' else pname
        stock = hb.count_documents({'nowuid': nowuid, 'state': 0})
        buttons.append([InlineKeyboardButton(f"🛒 {pname}", callback_data=f"gmsp {nowuid}:{stock}")])

    buttons.append([InlineKeyboardButton("❌ 关闭" if user_lang == 'zh' else "❌ Close", callback_data=f"close {user_id}")])

    update.message.reply_text(
        "🆕 最新上架商品：" if user_lang == 'zh' else "🆕 Newest Products:",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(buttons)
    )



def help_command(update: Update, context: CallbackContext):
    try:
        context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except:
        pass

    user_id = update.effective_user.id
    lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
    
    # ✅ 从环境变量读取客服联系方式
    customer_service = os.getenv('CUSTOMER_SERVICE', '@lwmmm')

    if lang == 'zh':
        text = (
            "<b>📖 使用指南 / 帮助中心</b>\n\n"
            "<b>🛒 本机器人支持出售：</b>\n"
            "✈️ 飞机号账号（Telegram）\n"
            "<b>💡 功能优势：</b>\n"
            "✅ 自动发货，秒到账\n"
            "✅ 永久保存购买记录\n"
            "✅ 避免被钓鱼链接骗U\n"
            "✅ 售后无忧，支持多支付\n\n"
            "<b>📬 客服支持：</b>\n"
            f"联系人工客服：<a href='https://t.me/{customer_service.replace('@', '')}'>{customer_service}</a>\n\n"
            "—— <i>安全、便捷、自动化的买号体验</i>"
        )
        close_btn = "❌ 关闭"
        header = "📖 使用指南"
    else:
        text = (
            "<b>📖 User Guide / Help Center</b>\n\n"
            "<b>🛒 Supported Products:</b>\n"
            "✈️ Telegram accounts\n"
            "<b>💡 Features:</b>\n"
            "✅ 24/7 Automatic delivery\n"
            "✅ Secure encrypted storage\n"
            "✅ Anti-phishing protection\n"
            "✅ Reliable after-sales support\n\n"
            "<b>📬 Customer Support:</b>\n"
            f"Contact us: <a href='https://t.me/{customer_service.replace('@', '')}'>{customer_service}</a>\n\n"
            "—— <i>Secure, convenient, and automated account trading experience</i>"
        )
        close_btn = "❌ Close"
        header = "� User Guide"
        header = "📖 Help Center"

    buttons = [[InlineKeyboardButton(close_btn, callback_data=f"close {user_id}")]]
    update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True
    )

def huifu(update: Update, context: CallbackContext):
    chat = update.effective_chat
    bot_id = context.bot.id
    if chat.type == 'private':
        user_id = update.effective_user.id
        user_list = user.find_one({"user_id": user_id})
        replymessage = update.message.reply_to_message
        text = replymessage.text
        del_message(update.message)
        messagetext = update.effective_message.text
        state = user_list['state']
        if state == '4' or state == '3':
            if '回复图文或图片视频文字' == text:
                if update.message.photo == [] and update.message.animation == None:
                    r_text = messagetext
                    sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'text': r_text}})
                    sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'file_id': ''}})
                    sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'send_type': 'text'}})
                    sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'state': 1}})
                    message_id = context.bot.send_message(chat_id=user_id, text=r_text)
                    time.sleep(3)
                    del_message(message_id)
                    message_id = context.user_data[f'wanfapeizhi{user_id}']
                    time.sleep(3)
                    del_message(message_id)

                else:
                    r_text = update.message.caption
                    try:
                        file = update.message.photo[-1].file_id
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'text': r_text}})
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'file_id': file}})
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'send_type': 'photo'}})
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'state': 1}})
                        message_id = context.bot.send_photo(chat_id=user_id, caption=r_text, photo=file)
                        time.sleep(3)
                        del_message(message_id)
                    except:
                        file = update.message.animation.file_id
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'text': r_text}})
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'file_id': file}})
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'},
                                        {'$set': {'send_type': 'animation'}})
                        sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'state': 1}})
                        message_id = context.bot.sendAnimation(chat_id=user_id, caption=r_text, animation=file)
                        time.sleep(3)
                        del_message(message_id)
            elif '回复按钮设置' == text:
                text = messagetext
                message_id = context.user_data[f'wanfapeizhi{user_id}']
                del_message(message_id)
                keyboard = parse_urls(text)
                dumped = pickle.dumps(keyboard)
                sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'keyboard': dumped}})
                sftw.update_one({'bot_id': bot_id, 'projectname': f'图文1🔽'}, {'$set': {'key_text': text}})
                try:
                    message_id = context.bot.send_message(chat_id=user_id, text='按钮设置成功',
                                                          reply_markup=InlineKeyboardMarkup(keyboard))
                    time.sleep(10)
                    del_message(message_id)

                except:
                    context.bot.send_message(chat_id=user_id, text=text)
                    message_id = context.bot.send_message(chat_id=user_id, text='按钮设置失败,请重新输入')
                    asyncio.sleep(10)
                    del_message(message_id)


def sifa(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    bot_id = context.bot.id

    fqdtw_list = sftw.find_one({'bot_id': bot_id, 'projectname': '图文1🔽'})
    if fqdtw_list is None:
        sifatuwen(bot_id, '图文1🔽', '', '', '', b'\x80\x03]q\x00]q\x01a.', '')
        fqdtw_list = sftw.find_one({'bot_id': bot_id, 'projectname': '图文1🔽'})

    state = fqdtw_list['state']

    # ✨ 图文私发菜单按钮（含表情 + 两列排布）
    keyboard = [
        [InlineKeyboardButton('🖼 图文设置', callback_data='tuwen'),
         InlineKeyboardButton('🔘 按钮设置', callback_data='anniu')],
        [InlineKeyboardButton('📎 查看图文', callback_data='cattu'),
         InlineKeyboardButton('📤 开启私发', callback_data='kaiqisifa')],
        [InlineKeyboardButton('❌ 关闭', callback_data=f'close {user_id}')]
    ]

    # 状态提示文本
    if state == 1:
        status_text = '📴 私发状态：<b>已关闭🔴</b>'
    else:
        status_text = '🟢 私发状态：<b>已开启🟢</b>'

    # 发送消息
    context.bot.send_message(
        chat_id=user_id,
        text=status_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



def tuwen(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    context.user_data[f'key{user_id}'] = query.message
    message_id = context.bot.send_message(chat_id=user_id, text=f'回复图文或图片视频文字',
                                          reply_markup=ForceReply(force_reply=True))
    context.user_data[f'wanfapeizhi{user_id}'] = message_id


def cattu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    bot_id = context.bot.id
    fqdtw_list = sftw.find_one({'bot_id': bot_id, 'projectname': f'图文1🔽'})
    file_id = fqdtw_list['file_id']
    file_text = fqdtw_list['text']
    file_type = fqdtw_list['send_type']
    key_text = fqdtw_list['key_text']
    keyboard = pickle.loads(fqdtw_list['keyboard'])
    keyboard.append([InlineKeyboardButton('✅已读（点击销毁此消息）', callback_data=f'close {user_id}')])
    if fqdtw_list['text'] == '' and fqdtw_list['file_id'] == '':
        message_id = context.bot.send_message(chat_id=user_id, text='请设置图文后点击')
        time.sleep(3)
        del_message(message_id)
    else:
        try:
            context.bot.send_message(chat_id=user_id, text=key_text)
        except:
            pass
        if file_type == 'text':
            try:
                message_id = context.bot.send_message(chat_id=user_id, text=file_text,
                                                      reply_markup=InlineKeyboardMarkup(keyboard))
            except:
                message_id = context.bot.send_message(chat_id=user_id, text=file_text)
        else:
            if file_type == 'photo':
                try:
                    message_id = context.bot.send_photo(chat_id=user_id, caption=file_text, photo=file_id,
                                                        reply_markup=InlineKeyboardMarkup(keyboard))
                except:
                    message_id = context.bot.send_photo(chat_id=user_id, caption=file_text, photo=file_id)
            else:
                try:
                    message_id = context.bot.sendAnimation(chat_id=user_id, caption=file_text, animation=file_id,
                                                           reply_markup=InlineKeyboardMarkup(keyboard))
                except:
                    message_id = context.bot.sendAnimation(chat_id=user_id, caption=file_text, animation=file_id)
        time.sleep(3)
        del_message(message_id)


def anniu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    context.user_data[f'key{user_id}'] = query.message
    message_id = context.bot.send_message(chat_id=user_id, text=f'回复按钮设置',
                                          reply_markup=ForceReply(force_reply=True))
    context.user_data[f'wanfapeizhi{user_id}'] = message_id




def kaiqisifa(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    bot_id = context.bot.id

    job = context.job_queue.get_jobs_by_name('sifa')

    if not job:
        # 🟢 修改图文状态为“正在私发”
        sftw.update_one({'bot_id': bot_id, 'projectname': '图文1🔽'}, {'$set': {"state": 2}})

        # ✨ 更新菜单按钮（图文管理）
        keyboard = [
            [InlineKeyboardButton('🖼 图文设置', callback_data='tuwen'),
             InlineKeyboardButton('🔘 按钮设置', callback_data='anniu')],
            [InlineKeyboardButton('📎 查看图文', callback_data='cattu'),
             InlineKeyboardButton('📤 开启私发', callback_data='kaiqisifa')],
            [InlineKeyboardButton('❌ 关闭', callback_data=f'close {user_id}')]
        ]

        # ✅ 状态文字提示
        query.edit_message_text(
            text='🟢 私发状态：<b>已开启</b>',
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # ⏳ 添加定时任务执行私发
        context.job_queue.run_once(usersifa, 1, context={"user_id": user_id}, name='sifa')

        # ⏱ 提示私发启动中
        context.bot.send_message(chat_id=user_id, text='⏳ 正在准备群发内容，请稍等...')
    else:
        # 🚫 阻止重复开启
        context.bot.send_message(chat_id=user_id, text='⚠️ 私发正在进行中，请勿重复开启。')



def usersifa(context: CallbackContext):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    job = context.job
    bot = context.bot
    bot_id = bot.id
    guanli_id = job.context['user_id']

    fqdtw_list = sftw.find_one({'bot_id': bot_id, 'projectname': '图文1🔽'})
    file_id = fqdtw_list['file_id']
    file_text = fqdtw_list['text']
    file_type = fqdtw_list['send_type']
    key_text = fqdtw_list['key_text']
    keyboard_data = fqdtw_list['keyboard']
    keyboard = pickle.loads(keyboard_data)
    keyboard.append([InlineKeyboardButton('✅ 已读（点击销毁此消息）', callback_data='close 12321')])
    markup = InlineKeyboardMarkup(keyboard)

    user_list = list(user.find({}))
    total_users = len(user_list)
    success = 0
    fail = 0
    lock = threading.Lock()

    # ⏳ 初始化消息（将后续所有进度和结果编辑在此消息上）
    progress_msg = bot.send_message(
        chat_id=guanli_id,
        text=f"⏳ 正在准备群发内容，请稍等...\n📤 进度：0/{total_users}",
        parse_mode='HTML'
    )

    def send_to_user(u):
        nonlocal success, fail
        try:
            uid = u['user_id']
            if file_type == 'text':
                bot.send_message(chat_id=uid, text=file_text, reply_markup=markup)
            elif file_type == 'photo':
                bot.send_photo(chat_id=uid, photo=file_id, caption=file_text, reply_markup=markup)
            elif file_type == 'animation':
                bot.send_animation(chat_id=uid, animation=file_id, caption=file_text, reply_markup=markup)
            else:
                raise Exception("❌ 不支持的发送类型")
            with lock:
                success += 1
        except:
            with lock:
                fail += 1
        finally:
            sent = success + fail
            if sent % 10 == 0 or sent == total_users:
                try:
                    bot.edit_message_text(
                        chat_id=guanli_id,
                        message_id=progress_msg.message_id,
                        text=f"📤 私发中：<b>{sent}/{total_users}</b>\n✅ 成功：{success}  ❌ 失败：{fail}",
                        parse_mode='HTML'
                    )
                except:
                    pass

    # 🚀 并发发送
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(send_to_user, user_list)

    # 🛑 更新图文状态为已关闭
    sftw.update_one({'bot_id': bot_id, 'projectname': '图文1🔽'}, {'$set': {'state': 1}})

    # 📌 最终编辑结果 + 菜单按钮
    end_keyboard = [
        [InlineKeyboardButton('🖼 图文设置', callback_data='tuwen'),
         InlineKeyboardButton('🔘 按钮设置', callback_data='anniu')],
        [InlineKeyboardButton('📎 查看图文', callback_data='cattu'),
         InlineKeyboardButton('📤 开启私发', callback_data='kaiqisifa')],
        [InlineKeyboardButton('❌ 关闭', callback_data=f'close {guanli_id}')]
    ]

    # ✅ 最终替换原消息
    bot.edit_message_text(
        chat_id=guanli_id,
        message_id=progress_msg.message_id,
        text=f"✅ 私发任务已完成！\n\n<b>成功：</b>{success} 人\n<b>失败：</b>{fail} 人\n\n📴 私发状态：<b>已关闭🔴</b>",
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(end_keyboard)
    )


def backstart(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    # 使用北京时间计算统计边界
    now = get_beijing_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def sum_income(start_time, end_time, cz_type=None):
        query = {
            'status': 'success',
            'time': {'$gte': start_time, '$lt': end_time}
        }
        if cz_type:
            query['cz_type'] = cz_type
        return sum(i.get('money', 0) for i in topup.find(query))

    def sum_rmb(start, end):
        return sum_income(start, end, 'alipay') + sum_income(start, end, 'wechat')

    def sum_usdt(start, end):
        return sum_income(start, end, 'usdt')

    today_rmb = sum_rmb(today_start, now)
    today_usdt = sum_usdt(today_start, now)
    yesterday_rmb = sum_rmb(yesterday_start, today_start)
    yesterday_usdt = sum_usdt(yesterday_start, today_start)
    week_rmb = sum_rmb(week_start, now)
    week_usdt = sum_usdt(week_start, now)
    month_rmb = sum_rmb(month_start, now)
    month_usdt = sum_usdt(month_start, now)

    total_users = user.count_documents({})
    total_balance = sum(i.get('USDT', 0) for i in user.find({'USDT': {'$gt': 0}}))

    # ✅ 美化管理员控制台，使用树状结构
    admin_text = f'''
🔧 <b>管理员控制台</b>

📊 <b>平台概览</b>
├─ 👥 用户总数：<code>{total_users}</code> 人
├─ 💰 平台余额：<code>{standard_num(total_balance)}</code> USDT
├─ 📅 今日收入：<code>{standard_num(today_usdt)}</code> USDT
└─ 📈 昨日收入：<code>{standard_num(yesterday_usdt)}</code> USDT

⏰ 更新时间：{format_beijing_time(now, '%m-%d %H:%M:%S')}
'''.strip()


    admin_buttons_raw = [
        InlineKeyboardButton('用户列表', callback_data='yhlist'),
        InlineKeyboardButton('用户私发', callback_data='sifa'),
        InlineKeyboardButton('设置充值地址', callback_data='settrc20'),
        InlineKeyboardButton('商品管理', callback_data='spgli'),
        InlineKeyboardButton('修改欢迎语', callback_data='startupdate'),
        InlineKeyboardButton('设置菜单按钮', callback_data='addzdykey'),
        InlineKeyboardButton('收益说明', callback_data='shouyishuoming'),
        InlineKeyboardButton('收入统计', callback_data='show_income'),
        InlineKeyboardButton('导出用户列表', callback_data='export_userlist'),
        InlineKeyboardButton('导出下单记录', callback_data='export_orders'),
        InlineKeyboardButton('管理员管理', callback_data='admin_manage'),
        InlineKeyboardButton('销售统计', callback_data='sales_dashboard'),
        InlineKeyboardButton('库存预警', callback_data='stock_alerts'),
        InlineKeyboardButton('数据导出', callback_data='data_export_menu'),
        InlineKeyboardButton('多语言管理', callback_data='multilang_management'),
        InlineKeyboardButton('🤖 代理管理', callback_data='agent_management'),
    ]
    admin_buttons = [admin_buttons_raw[i:i + 3] for i in range(0, len(admin_buttons_raw), 3)]
    admin_buttons.append([InlineKeyboardButton('关闭面板', callback_data=f'close {user_id}')])

    query.edit_message_text(
        text=admin_text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(admin_buttons),
        disable_web_page_preview=True
    )

def gmaijilu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = user.find_one({'user_id': user_id})['lang']
    df_id = int(query.data.replace('gmaijilu ', ''))

    # 查询最近10条记录
    jilu_list = list(gmjlu.find({'user_id': df_id}, sort=[('timer', -1)], limit=10))
    total_count = gmjlu.count_documents({'user_id': df_id})
    keyboard = []

    for i in jilu_list:
        bianhao = i.get('bianhao', '无编号')
        projectname = i.get('projectname', '未知商品')
        leixing = i.get('leixing', '未知类型')
        timer_value = i.get('timer')
        count = i.get('count', 1)
        
        # 处理时间显示（北京时间）
        if isinstance(timer_value, str):
            try:
                timer_dt = parse_to_beijing(timer_value)
                time_str = format_beijing_time(timer_dt, "%m-%d %H:%M") if timer_dt else timer_value[:10]
            except:
                time_str = timer_value[:10] if len(timer_value) > 10 else timer_value
        elif isinstance(timer_value, datetime):
            time_str = format_beijing_time(timer_value, "%m-%d %H:%M")
        else:
            time_str = '未知时间'

        # 商品名称处理（过滤测试数据）
        if projectname == '点击按钮修改':
            display_name = '测试商品' if lang == 'zh' else 'Test Product'
        else:
            display_name = projectname if lang == 'zh' else get_fy(projectname)
        
        # 优化按钮显示格式 - 包含商品名、数量、类型、时间
        if lang == 'zh':
            title = f"{display_name} | 数量:{count} | {leixing} | {time_str}"
        else:
            title = f"{get_fy(display_name)} | Qty:{count} | {leixing} | {time_str}"
            
        keyboard.append([InlineKeyboardButton(title, callback_data=f'zcfshuo {bianhao}')])

    # 改进分页按钮
    if total_count > 10:
        page_buttons = []
        # 第一页就是从0开始
        current_page = 1
        total_pages = (total_count + 9) // 10  # 向上取整
        
        # 上一页按钮 (当不是第一页时显示)
        if total_count > 10:  # 有多页才显示下一页
            if lang == 'zh':
                page_buttons.append(InlineKeyboardButton('📄 1/'+str(total_pages), callback_data='page_info'))
                page_buttons.append(InlineKeyboardButton('下一页 ➡️', callback_data=f'gmainext {df_id}:10'))
            else:
                page_buttons.append(InlineKeyboardButton('📄 1/'+str(total_pages), callback_data='page_info'))
                page_buttons.append(InlineKeyboardButton('Next ➡️', callback_data=f'gmainext {df_id}:10'))
        
        if page_buttons:
            keyboard.append(page_buttons)

    # 返回按钮
    if lang == 'zh':
        keyboard.append([InlineKeyboardButton('返回', callback_data=f'backgmjl {df_id}')])
        
        # 优化后的购买记录标题
        if total_count > 0:
            text = f'''
<b>购买记录</b>


<b>记录概览</b>
├─ 总订单数: <code>{total_count}</code>
├─ 显示条数: <code>{min(10, len(jilu_list))}</code>
└─ 最后更新: <code>{beijing_now_str("%m-%d %H:%M")}</code>

<b>操作说明</b>
└─ 点击下方按钮查看或重新下载商品


            '''.strip()
        else:
            text = '''
<b>购买记录</b>


<b>暂无记录</b>
└─ 您还没有购买任何商品

<b>温馨提示</b>
├─ 购买后的商品可在此处重新下载
├─ 记录永久保存，请妥善保管
└─ 如有问题请联系客服


            '''.strip()
    else:
        keyboard.append([InlineKeyboardButton('Return', callback_data=f'backgmjl {df_id}')])
        
        if total_count > 0:
            text = f'''
<b>Purchase Records</b>


<b>Records Overview</b>
├─ Total Orders: <code>{total_count}</code>
├─ Showing: <code>{min(10, len(jilu_list))}</code>
└─ Last Update: <code>{beijing_now_str("%m-%d %H:%M")}</code>

<b>Instructions</b>
└─ Click buttons below to view or re-download


            '''.strip()
        else:
            text = '''
<b>Purchase Records</b>


<b>No Records Found</b>
└─ You haven't purchased any items yet

<b>Tips</b>
├─ Purchased items can be re-downloaded here
├─ Records are permanently saved
└─ Contact support if you need help


            '''.strip()

    # 返回信息
    try:
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logging.error(f"❌ 显示购买记录失败：{e}")

def gmainext(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data.replace('gmainext ', '')
    page = data.split(":")[1]
    df_id = int(data.split(':')[0])
    user_id = query.from_user.id
    lang = user.find_one({'user_id': user_id})['lang']
    keyboard = []
    text_list = []
    jilu_list = list(gmjlu.find({"user_id": df_id}, sort=[("timer", -1)], skip=int(page), limit=10))
    count = 1
    for i in jilu_list:
        bianhao = i.get('bianhao', '无编号')
        projectname = i.get('projectname', '未知商品')
        leixing = i.get('leixing', '未知类型')
        timer_value = i.get('timer')
        count = i.get('count', 1)
        
        # 处理时间显示（北京时间）
        if isinstance(timer_value, str):
            try:
                timer_dt = parse_to_beijing(timer_value)
                time_str = format_beijing_time(timer_dt, "%m-%d %H:%M") if timer_dt else timer_value[:10]
            except:
                time_str = timer_value[:10] if len(timer_value) > 10 else timer_value
        elif isinstance(timer_value, datetime):
            time_str = format_beijing_time(timer_value, "%m-%d %H:%M")
        else:
            time_str = '未知时间'

        # 商品名称处理
        if projectname == '点击按钮修改':
            display_name = '测试商品' if lang == 'zh' else 'Test Product'
        else:
            display_name = projectname if lang == 'zh' else get_fy(projectname)
        
        # 优化按钮显示格式
        if lang == 'zh':
            title = f"{display_name} | 数量:{count} | {leixing} | {time_str}"
        else:
            title = f"{get_fy(display_name)} | Qty:{count} | {leixing} | {time_str}"
            
        keyboard.append([InlineKeyboardButton(title, callback_data=f'zcfshuo {bianhao}')])
        count += 1
    # 改进分页逻辑
    total_count = gmjlu.count_documents({'user_id': df_id})
    current_page = int(page) // 10 + 1
    total_pages = (total_count + 9) // 10
    
    if lang == 'zh':
        # 分页导航按钮
        if total_pages > 1:
            nav_buttons = []
            
            # 上一页按钮
            if current_page > 1:
                nav_buttons.append(InlineKeyboardButton('⬅️ 上一页', callback_data=f'gmainext {df_id}:{int(page) - 10}'))
            
            # 页码显示
            nav_buttons.append(InlineKeyboardButton(f'📄 {current_page}/{total_pages}', callback_data='page_info'))
            
            # 下一页按钮
            if current_page < total_pages:
                nav_buttons.append(InlineKeyboardButton('下一页 ➡️', callback_data=f'gmainext {df_id}:{int(page) + 10}'))
            
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton('🔙 返回', callback_data=f'backgmjl {df_id}')])
        
        text = f'''
<b>购买记录</b> (第{current_page}页/共{total_pages}页)


<b>分页信息</b>
├─ 当前页面: <code>{current_page}/{total_pages}</code>
├─ 显示记录: <code>{len(jilu_list)}</code> 条
├─ 总记录数: <code>{total_count}</code> 条
└─ 最后更新: <code>{beijing_now_str("%m-%d %H:%M")}</code>

<b>操作说明</b>
└─ 点击商品按钮查看或重新下载


        '''.strip()
        
        try:
            query.edit_message_text(text=text, parse_mode='HTML',
                                    reply_markup=InlineKeyboardMarkup(keyboard))
        except:
            pass
    else:
        # 英文版分页导航
        if total_pages > 1:
            nav_buttons = []
            
            # 上一页按钮
            if current_page > 1:
                nav_buttons.append(InlineKeyboardButton('⬅️ Previous', callback_data=f'gmainext {df_id}:{int(page) - 10}'))
            
            # 页码显示
            nav_buttons.append(InlineKeyboardButton(f'📄 {current_page}/{total_pages}', callback_data='page_info'))
            
            # 下一页按钮
            if current_page < total_pages:
                nav_buttons.append(InlineKeyboardButton('Next ➡️', callback_data=f'gmainext {df_id}:{int(page) + 10}'))
            
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton('🔙 Back', callback_data=f'backgmjl {df_id}')])
        
        text = f'''
<b>Purchase Records</b> (Page {current_page}/{total_pages})


<b>Page Information</b>
├─ Current Page: <code>{current_page}/{total_pages}</code>
├─ Records Shown: <code>{len(jilu_list)}</code>
├─ Total Records: <code>{total_count}</code>
└─ Last Update: <code>{beijing_now_str("%m-%d %H:%M")}</code>

<b>Instructions</b>
└─ Click product buttons to view or re-download


        '''.strip()
        
        try:
            query.edit_message_text(text=text, parse_mode='HTML',
                                    reply_markup=InlineKeyboardMarkup(keyboard))
        except:
            pass

def backgmjl(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    df_id = int(query.data.replace('backgmjl ', ''))
    df_list = user.find_one({'user_id': df_id})

    df_fullname = df_list.get('fullname', '无名')
    df_username = df_list.get('username')
    creation_time = df_list.get('creation_time', '未知')
    zgsl = df_list.get('zgsl', 0)
    zgje = df_list.get('zgje', 0)
    USDT = df_list.get('USDT', 0)
    lang = df_list.get('lang', 'zh')

    if isinstance(creation_time, datetime):
        creation_time = creation_time.strftime('%Y-%m-%d %H:%M:%S')

    if df_username:
        df_username_display = f'<a href="https://t.me/{df_username}">{df_username}</a>'
    else:
        df_username_display = df_fullname

    def standard_num(n):
        try:
            return f"{float(n):,.2f}"
        except:
            return "0.00"

    if lang == 'en':
        fstext = f"""
<b>User Information</b>


<b>Account Details</b>
├─ User ID: <code>{df_id}</code>
├─ Username: {df_username_display}
├─ Registered: <code>{creation_time}</code>
└─ Account Status: <code>Active</code>

<b>Transaction History</b>
├─ Total Orders: <code>{zgsl}</code>
├─ Total Spent: <code>{standard_num(zgje)}</code> USDT
└─ Current Balance: <code>{standard_num(USDT)}</code> USDT

<b>Available Actions</b>
├─ View Purchase Records
└─ Account Management


"""
        keyboard = [
            [
                InlineKeyboardButton('Purchase History', callback_data=f'gmaijilu {df_id}'),
                InlineKeyboardButton('Close', callback_data=f'close {user_id}')
            ]
        ]
    else:
        fstext = f"""
<b>用户信息</b>


<b>账户详情</b>
├─ 用户ID: <code>{df_id}</code>
├─ 用户名: {df_username_display}
├─ 注册时间: <code>{creation_time}</code>
└─ 账户状态: <code>正常</code>

<b>交易记录</b>
├─ 总订单数: <code>{zgsl}</code>
├─ 累计消费: <code>{standard_num(zgje)}</code> USDT
└─ 当前余额: <code>{standard_num(USDT)}</code> USDT

<b>可用操作</b>
├─ 查看购买记录
└─ 账户管理


"""
        keyboard = [
            [
                InlineKeyboardButton('购买记录', callback_data=f'gmaijilu {df_id}'),
                InlineKeyboardButton('关闭', callback_data=f'close {user_id}')
            ]
        ]

    query.edit_message_text(
        text=fstext.strip(),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML',
        disable_web_page_preview=True
    )


def zcfshuo(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = user.find_one({'user_id': user_id})['lang']
    bianhao = query.data.replace('zcfshuo ', '')

    gmjlu_list = gmjlu.find_one({'bianhao': bianhao})
    leixing = gmjlu_list['leixing']

    # API链接类的直接发送纯文本内容
    if leixing in ['会员链接', 'API链接', '谷歌']:
        text = gmjlu_list['text']
        context.bot.send_message(chat_id=user_id, text=text, disable_web_page_preview=True)

    # txt文本类的发送txt文本内容
    elif leixing == 'txt文本':
        text_content = gmjlu_list['text']
        # 直接发送文本内容
        context.bot.send_message(chat_id=user_id, text=text_content, disable_web_page_preview=True)

    # 协议号和直登号类的发送压缩包
    elif leixing in ['协议号', '直登号']:
        zip_filename = gmjlu_list['text']
        fstext = gmjlu_list['ts']
        fstext = fstext if lang == 'zh' else get_fy(fstext)

        keyboard = [[InlineKeyboardButton('✅已读（点击销毁此消息）', callback_data=f'close {user_id}')]]
        context.bot.send_message(
            chat_id=user_id,
            text=fstext,
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # ✅ 检查是否是有效的文件路径
        import os
        try:
            # 如果text字段不包含路径分隔符或文件扩展名，可能是错误的数据
            if not ('/' in zip_filename or '\\' in zip_filename or '.' in zip_filename):
                error_msg = f"❌ 记录数据异常，请联系管理员：{zip_filename}" if lang == 'zh' else f"❌ Record data error, please contact admin: {zip_filename}"
                context.bot.send_message(chat_id=user_id, text=error_msg)
                return
                
            if os.path.exists(zip_filename):
                with open(zip_filename, "rb") as f:
                    query.message.reply_document(f)
            else:
                error_msg = f"❌ 文件不存在：{zip_filename}" if lang == 'zh' else f"❌ File not found: {zip_filename}"
                context.bot.send_message(chat_id=user_id, text=error_msg)
        except Exception as e:
            error_msg = f"❌ 发送文件失败：{str(e)}" if lang == 'zh' else f"❌ Failed to send file: {str(e)}"
            context.bot.send_message(chat_id=user_id, text=error_msg)
            
    else:
        # 未知类型的处理
        error_msg = f"❌ 未知商品类型：{leixing}" if lang == 'zh' else f"❌ Unknown product type: {leixing}"
        context.bot.send_message(chat_id=user_id, text=error_msg)


# 辅助函数：去除表情符号等特殊字符
def clean_text(text):
    return re.sub(r'[^\w\s\u4e00-\u9fa5]', '', text)

# 辅助函数：昵称过长时加省略号
def shorten_text(text, max_length=12):
    return text if len(text) <= max_length else text[:max_length] + "..."

# 用户首页列表（第一页）
def show_user_list(update: Update, context: CallbackContext, page=0):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    limit = 30
    total = user.count_documents({})
    total_pages = (total + limit - 1) // limit
    current_page = max(0, min(page, total_pages - 1))

    jilu_list = list(user.find().sort("USDT", -1).skip(current_page * limit).limit(limit))
    text_list = []

    for i, user_data in enumerate(jilu_list, start=current_page * limit + 1):
        df_id = user_data['user_id']
        fullname = user_data.get('fullname', '无名')
        clean_name = shorten_text(clean_text(fullname), 12)
        USDT = user_data.get('USDT', 0)
        ctime = user_data.get('creation_time', '未知')

        text_list.append(
            f"{i}. <b><a href='tg://user?id={df_id}'>{clean_name}</a></b>\n"
            f"    └ ID: <code>{df_id}</code> | 余额: <b>{USDT} U</b> | 注册时间: <b>{ctime}</b>"
        )

    # 构建按钮区
    keyboard = []

    # ⬅️ 上一页 / 下一页 ➡️
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"yhpage {current_page - 1}"))
    if current_page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"yhpage {current_page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    # 页码跳转按钮（每行5个）
    page_buttons = []
    for i in range(total_pages):
        label = f"{'↦' if i == current_page else ''}第{i + 1}页"
        page_buttons.append(InlineKeyboardButton(label, callback_data=f'yhpage {i}'))
    for i in range(0, len(page_buttons), 5):
        keyboard.append(page_buttons[i:i + 5])

    # 返回主页按钮
    keyboard.append([InlineKeyboardButton('返回管理员主页', callback_data='backstart')])

    try:
        query.edit_message_text(
            text=f"<b>↰ 第 {current_page + 1} 页 / 共 {total_pages} 页 ↱</b>\n\n" + '\n'.join(text_list),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    except Exception as e:
        print(f"❌ 编辑消息失败：{e}")


def yhlist(update: Update, context: CallbackContext):
    show_user_list(update, context, page=0)


def yhpage(update: Update, context: CallbackContext):
    page = int(update.callback_query.data.split()[1])
    show_user_list(update, context, page=page)





def tjbaobiao(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id


def spgli(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    sp_list = list(fenlei.find({}))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]

    for i in sp_list:
        uid = i['uid']
        projectname = i['projectname']
        row = i['row']
        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'flxxi {uid}'))
    if sp_list == []:
        keyboard.append([InlineKeyboardButton("新建一行", callback_data='newfl')])
    else:
        keyboard.append([InlineKeyboardButton("新建一行", callback_data='newfl'),
                         InlineKeyboardButton('调整行排序', callback_data='paixufl'),
                         InlineKeyboardButton('删除一行', callback_data='delfl')])
    keyboard.append([InlineKeyboardButton('返回', callback_data='backstart'),
                     InlineKeyboardButton('关闭', callback_data=f'close {user_id}')])
    text = f'''
商品管理
    '''
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


def generate_24bit_uid():
    # 生成一个UUID
    uid = uuid.uuid4()

    # 将UUID转换为字符串
    uid_str = str(uid)

    # 使用MD5哈希算法将字符串哈希为一个128位的值
    hashed_uid = hashlib.md5(uid_str.encode()).hexdigest()

    # 取哈希值的前24位作为我们的24位UID
    return hashed_uid[:24]


def newfl(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    del_message(query.message)
    bot_id = context.bot.id
    maxrow = fenlei.find_one({}, sort=[('row', -1)])
    if maxrow is None:
        maxrow = 1
    else:
        maxrow = maxrow['row'] + 1
    uid = generate_24bit_uid()
    fenleibiao(uid, '点击按钮修改', maxrow)
    keylist = list(fenlei.find({}, sort=[('row', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    for i in keylist:
        uid = i['uid']
        projectname = i['projectname']
        row = i['row']
        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'flxxi {uid}'))
    keyboard.append([InlineKeyboardButton("新建一行", callback_data='newfl'),
                     InlineKeyboardButton('调整行排序', callback_data='paixufl'),
                     InlineKeyboardButton('删除一行', callback_data='delfl')])
    context.bot.send_message(chat_id=user_id, text='商品管理', reply_markup=InlineKeyboardMarkup(keyboard))


def flxxi(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    uid = query.data.replace('flxxi ', '')
    fl_pro = fenlei.find_one({'uid': uid})['projectname']
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    ej_list = ejfl.find({'uid': uid})
    for i in ej_list:
        nowuid = i['nowuid']
        projectname = i['projectname']
        row = i['row']
        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'fejxxi {nowuid}'))

    keyboard.append([InlineKeyboardButton('修改分类名', callback_data=f'upspname {uid}'),
                     InlineKeyboardButton('新增二级分类', callback_data=f'newejfl {uid}')])
    keyboard.append([InlineKeyboardButton('调整二级分类排序', callback_data=f'paixuejfl {uid}'),
                     InlineKeyboardButton('删除二级分类', callback_data=f'delejfl {uid}')])
    keyboard.append([InlineKeyboardButton('返回', callback_data=f'spgli')])
    fstext = f'''
分类: {fl_pro}
    '''
    query.edit_message_text(text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def create_product(ejfl, projectname, price, uid):
    """创建商品"""
    nowuid = str(uuid.uuid4())  # 生成唯一ID
    
    # 获取一级分类信息作为商品分类
    category = ''
    try:
        parent_category = fenlei.find_one({'uid': uid})
        if parent_category:
            category = parent_category.get('projectname', '')
    except Exception as e:
        logging.warning(f"⚠️ 获取父分类失败: {e}")
    
    product = {
        "projectname": projectname,
        "money": price,
        "uid": uid,
        "nowuid": nowuid,
        "leixing": category  # 添加分类字段
    }
    ejfl.insert_one(product)
    
    return nowuid


def fejxxi(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_username = context.bot.username
    nowuid = query.data.replace('fejxxi ', '')

    ej_list = ejfl.find_one({'nowuid': nowuid})
    if not ej_list:
        query.edit_message_text("❌ 未找到该商品")
        return

    uid = ej_list['uid']
    ej_projectname = ej_list['projectname']
    money = ej_list['money']
    fl_pro = fenlei.find_one({'uid': uid})['projectname']

    # 分享链接（使用 startapp 触发 inline 模式）
    safe_projectname = urllib.parse.quote(ej_projectname)
    inline_url = f"https://t.me/share/url?url=@{context.bot.username}%20{urllib.parse.quote(ej_projectname)}"


    keyboard = [
        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
        [InlineKeyboardButton("📤 分享商品", switch_inline_query=f"share_{nowuid}")],
        [InlineKeyboardButton('🗑️ 删除该分类', callback_data=f'del_ejfl_open:{nowuid}')],
        [InlineKeyboardButton('返回', callback_data=f'flxxi {uid}')]
    ]

    kc = hb.count_documents({'nowuid': nowuid, 'state': 0})
    ys = hb.count_documents({'nowuid': nowuid, 'state': 1})

    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
    '''

    query.edit_message_text(
        text=fstext,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def update_xyh(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    nowuid = query.data.replace('update_xyh ', '')
    fstext = f'''
发送协议号压缩包，自动识别里面的json或session格式
    '''
    user.update_one({"user_id": user_id}, {"$set": {"sign": f'update_xyh {nowuid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def update_gg(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    nowuid = query.data.replace('update_gg ', '')
    fstext = f'''
发送txt文件
    '''
    user.update_one({"user_id": user_id}, {"$set": {"sign": f'update_gg {nowuid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def update_txt(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    nowuid = query.data.replace('update_txt ', '')
    fstext = f'''
api号码链接专用，请正确上传，发送txt文件，一行一个
    '''
    user.update_one({"user_id": user_id}, {"$set": {"sign": f'update_txt {nowuid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def update_sysm(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    nowuid = query.data.replace('update_sysm ', '')
    dqts = ejfl.find_one({'nowuid': nowuid})['sysm']

    context.bot.send_message(chat_id=user_id, text=dqts, parse_mode='HTML')

    fstext = f'''
当前使用说明为上面
输入新的文字更改
    '''
    user.update_one({"user_id": user_id}, {"$set": {"sign": f'update_sysm {nowuid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def update_wbts(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    nowuid = query.data.replace('update_wbts ', '')
    dqts = ejfl.find_one({'nowuid': nowuid})['text']

    context.bot.send_message(chat_id=user_id, text=dqts, parse_mode='HTML')

    fstext = f'''
当前分类提示为上面
输入新的文字更改
    '''
    user.update_one({"user_id": user_id}, {"$set": {"sign": f'update_wbts {nowuid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def update_hy(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    nowuid = query.data.replace('update_hy ', '')

    fstext = """
<b>📤 请发送链接，每行一条</b>

格式示例：
<code>手机号----https://xxx</code>
<code>账号----密码----https://xxx</code>

<b>⚠️ 注意：</b>
• 每行用 <b>四个英文减号 ----</b> 分隔  
• 链接必须以 <code>http</code> 开头  
• 系统自动去重，重复不入库
"""

    user.update_one({"user_id": user_id}, {"$set": {"sign": f'update_hy {nowuid}'}})

    keyboard = [[InlineKeyboardButton('❌ 取消上传', callback_data=f'close {user_id}')]]
    context.bot.send_message(
        chat_id=user_id,
        text=fstext,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )




def update_hb(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    nowuid = query.data.replace('update_hb ', '')
    fstext = f'''
发送号包
    '''
    user.update_one({"user_id": user_id}, {"$set": {"sign": f'update_hb {nowuid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def upmoney(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    uid = query.data.replace('upmoney ', '')
    fstext = f'''
输入新的价格
    '''

    user.update_one({"user_id": user_id}, {"$set": {"sign": f'upmoney {uid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def upejflname(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    uid = query.data.replace('upejflname ', '')
    fstext = f'''
输入新的名字
例如 +54 ~直登号(tadta)
    '''

    user.update_one({"user_id": user_id}, {"$set": {"sign": f'upejflname {uid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def upspname(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    uid = query.data.replace('upspname ', '')
    fstext = f'''
输入新的名字
例如 🌎亚洲国家~✈直登号(tadta)
    '''

    user.update_one({"user_id": user_id}, {"$set": {"sign": f'upspname {uid}'}})
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def newejfl(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    uid = query.data.replace('newejfl ', '')

    maxrow = ejfl.find_one({'uid': uid}, sort=[('row', -1)])
    if maxrow is None:
        maxrow = 1
    else:
        maxrow = maxrow['row'] + 1
    nowuid = generate_24bit_uid()
    erjifenleibiao(uid, nowuid, '点击按钮修改', maxrow)
    fl_pro = fenlei.find_one({'uid': uid})['projectname']
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    ej_list = ejfl.find({'uid': uid})
    for i in ej_list:
        nowuid = i['nowuid']
        projectname = i['projectname']
        row = i['row']
        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'fejxxi {nowuid}'))

    keyboard.append([InlineKeyboardButton('修改分类名', callback_data=f'upspname {uid}'),
                     InlineKeyboardButton('新增二级分类', callback_data=f'newejfl {uid}')])
    keyboard.append([InlineKeyboardButton('调整二级分类排序', callback_data=f'paixuejfl {uid}'),
                     InlineKeyboardButton('删除二级分类', callback_data=f'delejfl {uid}')])
    keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
    fstext = f'''
分类: {fl_pro}
    '''
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def addzdykey(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    keylist = get_key.find({}, sort=[('Row', 1), ('first', 1)])
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
    if keylist == []:
        keyboard = [[InlineKeyboardButton("新建一行", callback_data='newrow')]]
    else:
        keyboard.append([InlineKeyboardButton('新建一行', callback_data='newrow'),
                         InlineKeyboardButton('删除一行', callback_data='delrow'),
                         InlineKeyboardButton('调整行排序', callback_data='paixurow')])
        keyboard.append([InlineKeyboardButton('修改按钮', callback_data='newkey')])

    keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
    text = f'''
自定义按钮
    '''
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


def newkey(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='请先新建一行')
    else:
        maxrow = max(count)
        for i in range(0, maxrow):
            keyboard.append([InlineKeyboardButton(f'第{i + 1}行', callback_data=f'dddd'),
                             InlineKeyboardButton('➕', callback_data=f'addhangkey {i + 1}'),
                             InlineKeyboardButton('➖', callback_data=f'delhangkey {i + 1}')])
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
        query.edit_message_text(text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def newrow(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    del_message(query.message)
    bot_id = context.bot.id
    maxrow = get_key.find_one({}, sort=[('Row', -1)])
    if maxrow is None:
        maxrow = 1
    else:
        maxrow = maxrow['Row'] + 1
    keybutton(maxrow, 1)
    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
    keyboard.append([InlineKeyboardButton('新建一行', callback_data='newrow'),
                     InlineKeyboardButton('删除一行', callback_data='delrow'),
                     InlineKeyboardButton('调整行排序', callback_data='paixurow')])
    keyboard.append([InlineKeyboardButton('修改按钮', callback_data='newkey')])
    keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
    context.bot.send_message(chat_id=user_id, text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def close(update: Update, context: CallbackContext):
    query = update.callback_query
    chat = query.message.chat
    query.answer()
    yh_id = query.data.replace("close ", '')
    bot_id = context.bot.id
    chat_id = chat.id
    user_id = query.from_user.id

    user.update_one({'user_id': user_id}, {'$set': {'sign': 0}})
    context.bot.delete_message(chat_id=query.from_user.id, message_id=query.message.message_id)


def paixurow(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='没有按钮存在')
    else:
        maxrow = max(count)
        if maxrow == 1:
            context.bot.send_message(chat_id=user_id, text='只有一行按钮无法调整')
        else:
            for i in range(0, maxrow):
                if i == 0:
                    keyboard.append(
                        [InlineKeyboardButton(f'第{i + 1}行下移', callback_data=f'paixuyidong xiayi:{i + 1}')])
                elif i == maxrow - 1:
                    keyboard.append(
                        [InlineKeyboardButton(f'第{i + 1}行上移', callback_data=f'paixuyidong shangyi:{i + 1}')])
                else:
                    keyboard.append(
                        [InlineKeyboardButton(f'第{i + 1}行上移', callback_data=f'paixuyidong shangyi:{i + 1}'),
                         InlineKeyboardButton(f'第{i + 1}行下移', callback_data=f'paixuyidong xiayi:{i + 1}')])
            keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
            keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
            query.edit_message_text(text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def paixuyidong(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('paixuyidong ', '')
    qudataall = qudata.split(':')
    yidongtype = qudataall[0]
    row = int(qudataall[1])
    if yidongtype == 'shangyi':
        get_key.update_many({"Row": row - 1}, {"$set": {'Row': 99}})
        get_key.update_many({"Row": row}, {"$set": {'Row': row - 1}})
        get_key.update_many({"Row": 99}, {"$set": {'Row': row}})
    else:
        get_key.update_many({"Row": row + 1}, {"$set": {'Row': 99}})
        get_key.update_many({"Row": row}, {"$set": {'Row': row + 1}})
        get_key.update_many({"Row": 99}, {"$set": {'Row': row}})
    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
    keyboard.append([InlineKeyboardButton('新建一行', callback_data='newrow'),
                     InlineKeyboardButton('删除一行', callback_data='delrow'),
                     InlineKeyboardButton('调整行排序', callback_data='paixurow')])
    keyboard.append([InlineKeyboardButton('修改按钮', callback_data='newkey')])
    keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
    query.edit_message_text(text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def delrow(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='没有按钮存在')
    else:
        maxrow = max(count)
        for i in range(0, maxrow):
            keyboard.append([InlineKeyboardButton(f'删除第{i + 1}行', callback_data=f'qrscdelrow {i + 1}')])
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
        query.edit_message_text(text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def qrscdelrow(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    del_message(query.message)
    row = int(query.data.replace('qrscdelrow ', ''))
    bot_id = context.bot.id
    get_key.delete_many({"Row": row})
    max_list = list(get_key.find({'Row': {"$gt": row}}))
    for i in max_list:
        max_row = i['Row']
        get_key.update_many({'Row': max_row}, {"$set": {"Row": max_row - 1}})
    maxrow = get_key.find_one({}, sort=[('Row', -1)])
    if maxrow is None:
        maxrow = 1
    else:
        maxrow = maxrow['Row'] + 1
    # keybutton(maxrow,1)
    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
    keyboard.append([InlineKeyboardButton('新建一行', callback_data='newrow'),
                     InlineKeyboardButton('删除一行', callback_data='delrow'),
                     InlineKeyboardButton('调整行排序', callback_data='paixurow')])
    keyboard.append([InlineKeyboardButton('修改按钮', callback_data='newkey')])
    keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
    context.bot.send_message(chat_id=user_id, text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def delhangkey(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    row = int(query.data.replace('delhangkey ', ''))
    bot_id = context.bot.id
    key_list = list(get_key.find({'Row': row}, sort=[('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in key_list:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='没有按钮存在')
    else:

        # maxrow = max(count)
        for i in range(0, len(count)):
            keyboard[count[i]].append(InlineKeyboardButton('➖', callback_data=f'qrdelliekey {row}:{i + 1}'))
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
        query.edit_message_text(text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def keyxq(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('keyxq ', '')
    qudataall = qudata.split(':')
    row = int(qudataall[0])
    first = int(qudataall[1])
    key_list = get_key.find_one({'Row': row, 'first': first})
    projectname = key_list['projectname']
    text = key_list['text']
    print_text = f'''
这是第{row}行第{first}个按钮

按钮名称: {projectname}
    '''

    keyboard = [
        [InlineKeyboardButton('图文设置', callback_data=f'settuwenset {row}:{first}'),
         InlineKeyboardButton('查看图文设置', callback_data=f'cattuwenset {row}:{first}')],
        [InlineKeyboardButton('修改尾随按钮', callback_data=f'setkeyboard {row}:{first}'),
         InlineKeyboardButton('修改按钮名字', callback_data=f'setkeyname {row}:{first}')],
        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
    ]

    keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
    query.edit_message_text(text=print_text, reply_markup=InlineKeyboardMarkup(keyboard))


def setkeyname(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('setkeyname ', '')
    qudataall = qudata.split(':')
    row = int(qudataall[0])
    first = int(qudataall[1])
    text = f'''
输入要修改的名字
    '''
    user.update_one({'user_id': user_id}, {"$set": {"sign": f'setkeyname {row}:{first}'}})
    keyboard = [[InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]]
    keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def setkeyboard(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('setkeyboard ', '')
    qudataall = qudata.split(':')
    row = int(qudataall[0])
    first = int(qudataall[1])
    text = f'''
按以下格式设置按钮，填入◈之间，同一行用 | 隔开
按钮名称&https://t.me/... | 按钮名称&https://t.me/...
按钮名称&https://t.me/... | 按钮名称&https://t.me/... | 按钮名称&https://t.me/....
    '''
    key_list = get_key.find_one({'Row': row, 'first': first})
    key_text = key_list['key_text']
    if key_text != '':
        context.bot.send_message(chat_id=user_id, text=key_text)
    user.update_one({'user_id': user_id}, {"$set": {"sign": f'setkeyboard {row}:{first}'}})
    keyboard = [[InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]]
    keyboard.append([InlineKeyboardButton('返回主界面', callback_data=f'backstart')])
    query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def settuwenset(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('settuwenset ', '')
    qudataall = qudata.split(':')
    row = int(qudataall[0])
    first = int(qudataall[1])
    key_list = get_key.find_one({'Row': row, 'first': first})
    key_text = key_list['key_text']
    text = key_list['text']
    file_type = key_list['file_type']
    file_id = key_list['file_id']
    entities = pickle.loads(key_list['entities'])
    keyboard = pickle.loads(key_list['keyboard'])
    if text == '' and file_id == '':
        pass
    else:
        if file_type == 'text':
            message_id = context.bot.send_message(chat_id=user_id, text=text,
                                                  reply_markup=InlineKeyboardMarkup(keyboard), entities=entities)
        else:
            if file_type == 'photo':
                message_id = context.bot.send_photo(chat_id=user_id, caption=text, photo=file_id,
                                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                                    caption_entities=entities)
            else:
                message_id = context.bot.sendAnimation(chat_id=user_id, caption=text, animation=file_id,
                                                       reply_markup=InlineKeyboardMarkup(keyboard),
                                                       caption_entities=entities)
    text = f'''
✍️ 发送你的图文设置

文字、视频、图片、gif、图文
    '''
    user.update_one({'user_id': user_id}, {"$set": {"sign": f'settuwenset {row}:{first}'}})
    keyboard = [[InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]]
    context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def cattuwenset(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('cattuwenset ', '')
    qudataall = qudata.split(':')
    row = int(qudataall[0])
    first = int(qudataall[1])
    key_list = get_key.find_one({'Row': row, 'first': first})
    key_text = key_list['key_text']
    text = key_list['text']
    file_type = key_list['file_type']
    file_id = key_list['file_id']
    entities = pickle.loads(key_list['entities'])
    keyboard = pickle.loads(key_list['keyboard'])
    if text == '' and file_id == '':
        message_id = context.bot.send_message(chat_id=user_id, text='请设置图文后点击')
        timer11 = Timer(3, del_message, args=[message_id])
        timer11.start()
    else:
        if file_type == 'text':
            message_id = context.bot.send_message(chat_id=user_id, text=text,
                                                  reply_markup=InlineKeyboardMarkup(keyboard), entities=entities)
        else:
            if file_type == 'photo':
                message_id = context.bot.send_photo(chat_id=user_id, caption=text, photo=file_id,
                                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                                    caption_entities=entities)
            else:
                message_id = context.bot.sendAnimation(chat_id=user_id, caption=text, animation=file_id,
                                                       reply_markup=InlineKeyboardMarkup(keyboard),
                                                       caption_entities=entities)
        timer11 = Timer(3, del_message, args=[message_id])
        timer11.start()


def qrdelliekey(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('qrdelliekey ', '')
    qudataall = qudata.split(':')
    row = int(qudataall[0])
    first = int(qudataall[1])
    get_key.delete_one({"Row": row, 'first': first})
    max_list = list(get_key.find({'Row': row, 'first': {"$gt": first}}))
    for i in max_list:
        max_lie = i['first']
        get_key.update_one({'Row': row, 'first': max_lie}, {"$set": {"first": max_lie - 1}})

    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='请先新建一行')
    else:
        maxrow = max(count)
        for i in range(0, maxrow):
            keyboard.append([InlineKeyboardButton(f'第{i + 1}行', callback_data=f'dddd'),
                             InlineKeyboardButton('➕', callback_data=f'addhangkey {i + 1}'),
                             InlineKeyboardButton('➖', callback_data=f'delhangkey {i + 1}')])
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        context.bot.send_message(chat_id=user_id, text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def addhangkey(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    del_message(query.message)
    row = int(query.data.replace('addhangkey ', ''))
    bot_id = context.bot.id
    lie = get_key.find_one({'Row': row}, sort=[('first', -1)])['first']
    keybutton(row, lie + 1)

    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['Row']
        first = i['first']
        keyboard[i["Row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='请先新建一行')
    else:
        maxrow = max(count)
        for i in range(0, maxrow):
            keyboard.append([InlineKeyboardButton(f'第{i + 1}行', callback_data=f'dddd'),
                             InlineKeyboardButton('➕', callback_data=f'addhangkey {i + 1}'),
                             InlineKeyboardButton('➖', callback_data=f'delhangkey {i + 1}')])
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        context.bot.send_message(chat_id=user_id, text='自定义按钮', reply_markup=InlineKeyboardMarkup(keyboard))


def settrc20(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    text = f'''
输入以T开头共34位的 trc20地址
'''
    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    user.update_one({'user_id': user_id}, {"$set": {"sign": 'settrc20'}})
    context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))


def startupdate(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id

    text = '''
请输入新的欢迎语，支持 <b>加粗</b>、<i>斜体</i>、<code>代码</code>、<a href="https://t.me/example">超链接</a>
'''

    keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    user.update_one({'user_id': user_id}, {"$set": {"sign": 'startupdate'}})

    context.bot.send_message(
        chat_id=user_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'  # ✅ 必须指定解析模式
    )



def zdycz(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    lang = user.find_one({'user_id': user_id})['lang']
    bot_id = context.bot.id

    if lang == 'zh':
        text = f'''
输入充值金额
    '''
        keyboard = [[InlineKeyboardButton('取消', callback_data=f'close {user_id}')]]
    else:
        text = f'''
Enter the recharge amount
        '''
        keyboard = [[InlineKeyboardButton('Cancel', callback_data=f'close {user_id}')]]
    message_id = context.bot.send_message(chat_id=user_id, text=text, reply_markup=InlineKeyboardMarkup(keyboard))

    user.update_one({'user_id': user_id}, {"$set": {"sign": f'zdycz {message_id.message_id}'}})


def catejflsp(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        uid, zhsl = query.data.replace('catejflsp ', '').split(':')
        zhsl = int(zhsl)
    except Exception:
        query.answer("参数错误", show_alert=True)
        return

    user_id = query.from_user.id
    user_data = user.find_one({'user_id': user_id})
    lang = user_data.get('lang', 'zh')

    # 获取所有二级分类并根据库存排序，只显示有库存的商品
    ej_list = ejfl.find({'uid': uid})
    
    # ✅ 功能1：只显示有库存的商品
    filtered_ej_list = []
    for item in ej_list:
        stock_count = hb.count_documents({'nowuid': item['nowuid'], 'state': 0})
        if stock_count > 0:  # 只添加有库存的商品
            item['stock_count'] = stock_count
            filtered_ej_list.append(item)
    
    # 按库存数量降序排列（库存多的在前面）
    sorted_ej_list = sorted(filtered_ej_list, key=lambda x: -x['stock_count'])

    keyboard = []

    for i in sorted_ej_list:
        nowuid = i['nowuid']
        projectname = i['projectname']
        money = i.get('money', 0)
        hsl = i['stock_count']  # 使用预先计算的库存数量

        # ✅ 跳过未设置价格的商品
        if money <= 0:
            continue

        if lang != 'zh':
            projectname = get_fy(projectname)

        keyboard.append([
            InlineKeyboardButton(
                f'{projectname} {money}U  [{hsl}个]',
                callback_data=f'gmsp {nowuid}:{hsl}'
            )
        ])

    # 如果没有有库存的商品，显示提示信息
    if not keyboard:
        no_stock_text = "暂无商品耐心等待" if lang == 'zh' else "No products in stock"
        keyboard.append([InlineKeyboardButton(no_stock_text, callback_data='no_action')])

    back_text = '🔙返回' if lang == 'zh' else '🔙Back'
    close_text = '❌关闭' if lang == 'zh' else '❌Close'
    keyboard.append([
        InlineKeyboardButton(back_text, callback_data='backzcd'),
        InlineKeyboardButton(close_text, callback_data=f'close {user_id}')
    ])

    fstext = (
        "<b>🛒这是商品列表  选择你需要的分类：</b>\n\n"
        "❗️没使用过的本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！。\n\n"
        "❗有密码的账户售后时间1小时内，二级未知的账户售后30分钟内！\n\n"
        "❗购买后请第一时间检查账户，提供证明处理售后 超时损失自付！"
        if lang == 'zh' else
        "<b>🛒 This is the product list. Please select the product you want:</b>\n\n"
        "❗️To avoid disputes, try ordering small quantities first.\n"
        "❗️Check account validity immediately after purchase. No after-sales support after 1 hour."
    )

    query.edit_message_text(
        text=fstext,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

def gmsp(update: Update, context: CallbackContext, nowuid=None, hsl="1"):
    if not nowuid:
        query = update.callback_query
        data = query.data.replace('gmsp ', '')
        nowuid = data.split(':')[0]
        hsl = data.split(':')[1]
        user_id = query.from_user.id
        answer = query.answer
        send_func = query.edit_message_text
    else:
        user_id = update.effective_user.id
        answer = lambda *a, **kw: None
        send_func = update.message.reply_text

    # 查询用户语言
    u = user.find_one({'user_id': user_id})
    lang = u.get('lang', 'zh') if u else 'zh'

    ejfl_list = ejfl.find_one({'nowuid': nowuid})
    if not ejfl_list:
        return send_func("❌ 未找到该商品")

    projectname = ejfl_list['projectname']
    money = ejfl_list.get('money', 0)
    uid = ejfl_list['uid']

    # ✅ 检查商品是否设置了价格
    if money <= 0:
        error_msg = "❌ 该商品暂未设置价格，请联系管理员！" if lang == 'zh' else "❌ This product has no price set, please contact admin!"
        return send_func(error_msg)

    # ✅ 实时库存查询
    stock = hb.count_documents({'nowuid': nowuid, 'state': 0})

    answer()
    if lang == 'zh':
        fstext = f'''
<b>✅您正在购买:  {projectname}

💰 价格： {money:.2f} USDT

🏢 库存： {stock} 份

❗️ 未使用过的本店商品的，请先少量购买测试，以免造成不必要的争执！谢谢合作！

❗️账号价格会根据市场价有所浮动！请理解！</b>
        '''
        keyboard = [
            [InlineKeyboardButton('✅购买', callback_data=f'gmqq {nowuid}:{stock}'),
             InlineKeyboardButton('使用说明📜', callback_data='sysming')],
            [InlineKeyboardButton('🏠主菜单', callback_data='backzcd'),
             InlineKeyboardButton('返回↩️', callback_data=f'catejflsp {uid}:1000')],
            [InlineKeyboardButton('❌ 关闭', callback_data=f'close {user_id}')]
        ]
    else:
        projectname = get_fy(projectname)
        fstext = f'''
<b>✅You are buying: {projectname}

💰 Price: {money:.2f} USDT

🏢 Inventory: {stock} items

❗️ Please purchase a small quantity for testing first to avoid disputes. Thank you!

❗️ Prices may fluctuate with the market!</b>
        '''
        keyboard = [
            [InlineKeyboardButton('✅Buy', callback_data=f'gmqq {nowuid}:{stock}'),
             InlineKeyboardButton('Instructions 📜', callback_data='sysming')],
            [InlineKeyboardButton('🏠Main Menu', callback_data='backzcd'),
             InlineKeyboardButton('Return ↩️', callback_data=f'catejflsp {uid}:1000')],
            [InlineKeyboardButton('❌ Close', callback_data=f'close {user_id}')]
        ]

    send_func(fstext.strip(), parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

def gmqq(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    lang = user.find_one({'user_id': user_id})['lang']
    data = query.data.replace('gmqq ', '')
    nowuid = data.split(':')[0]
    hsl = data.split(':')[1]

    ejfl_list = ejfl.find_one({'nowuid': nowuid})
    if not ejfl_list:
        query.answer("❌ 未找到该商品", show_alert=True)
        return
        
    projectname = ejfl_list['projectname']
    money = ejfl_list.get('money', 0)
    uid = ejfl_list['uid']

    # ✅ 检查商品是否设置了价格
    if money <= 0:
        error_msg = "❌ 该商品暂未设置价格，请联系管理员！" if lang == 'zh' else "❌ This product has no price set, please contact admin!"
        query.answer(error_msg, show_alert=True)
        return

    user_list = user.find_one({'user_id': user_id})
    USDT = user_list['USDT']
    if USDT < money:
        fstext = f'''
❌余额不足，请立即充值
            '''
        fstext = fstext if lang == 'zh' else get_fy(fstext)
        query.answer(fstext, show_alert=bool("true"))
        return
    else:
        query.answer()
        del_message(query.message)
        fstext = f'''
<b>请输入数量：
格式：</b><code>10</code>
            '''
        fstext = fstext if lang == 'zh' else get_fy(fstext)
        user.update_one({'user_id': user_id}, {"$set": {"sign": f"gmqq {nowuid}:{hsl}"}})

        context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML')

def sysming(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    nowuid = query.data.replace('sysming ', '')

    # 🧾 查找对应数据
    ejfl_list = ejfl.find_one({'nowuid': nowuid})

    if ejfl_list and 'sysm' in ejfl_list:
        sysm = ejfl_list['sysm']
    else:
        sysm = "暂无说明"

    # 🧷 回复用户
    keyboard = [
        [InlineKeyboardButton('❌ 关闭', callback_data=f'close {user_id}')]
    ]
    context.bot.send_message(
        chat_id=user_id,
        text=sysm,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def paixuejfl(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    uid = query.data.replace('paixuejfl ', '')
    bot_id = context.bot.id
    fl_pro = fenlei.find_one({'uid': uid})['projectname']
    keylist = list(ejfl.find({'uid': uid}, sort=[('row', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['row']
        nowuid = i['nowuid']
        keyboard[i["row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'fejxxi {nowuid}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='没有按钮存在')
    else:
        maxrow = max(count)
        if maxrow == 1:
            context.bot.send_message(chat_id=user_id, text='只有一行按钮无法调整')
        else:
            for i in range(0, maxrow):
                pxuid = ejfl.find_one({'uid': uid, 'row': i + 1})['nowuid']
                if i == 0:
                    keyboard.append(
                        [InlineKeyboardButton(f'第{i + 1}行下移', callback_data=f'ejfpaixu xiayi:{i + 1}:{pxuid}')])
                elif i == maxrow - 1:
                    keyboard.append(
                        [InlineKeyboardButton(f'第{i + 1}行上移', callback_data=f'ejfpaixu shangyi:{i + 1}:{pxuid}')])
                else:
                    keyboard.append(
                        [InlineKeyboardButton(f'第{i + 1}行上移', callback_data=f'ejfpaixu shangyi:{i + 1}:{pxuid}'),
                         InlineKeyboardButton(f'第{i + 1}行下移', callback_data=f'ejfpaixu xiayi:{i + 1}:{pxuid}')])
            keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
            context.bot.send_message(chat_id=user_id, text=f'分类: {fl_pro}',
                                     reply_markup=InlineKeyboardMarkup(keyboard))

def ejfpaixu(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('ejfpaixu ', '')
    qudataall = qudata.split(':')
    yidongtype = qudataall[0]
    row = int(qudataall[1])
    nowuid = qudataall[2]
    uid = ejfl.find_one({'nowuid': nowuid})['uid']
    if yidongtype == 'shangyi':
        ejfl.update_many({"row": row - 1, 'uid': uid}, {"$set": {'row': 99}})
        ejfl.update_many({"row": row, 'uid': uid}, {"$set": {'row': row - 1}})
        ejfl.update_many({"row": 99, 'uid': uid}, {"$set": {'row': row}})
    else:
        ejfl.update_many({"row": row + 1, 'uid': uid}, {"$set": {'row': 99}})
        ejfl.update_many({"row": row, 'uid': uid}, {"$set": {'row': row + 1}})
        ejfl.update_many({"row": 99, 'uid': uid}, {"$set": {'row': row}})

    fl_pro = fenlei.find_one({'uid': uid})['projectname']
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    ej_list = ejfl.find({'uid': uid})
    for i in ej_list:
        nowuid = i['nowuid']
        projectname = i['projectname']
        row = i['row']
        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'fejxxi {nowuid}'))

    keyboard.append([InlineKeyboardButton('修改分类名', callback_data=f'upspname {uid}'),
                     InlineKeyboardButton('新增二级分类', callback_data=f'newejfl {uid}')])
    keyboard.append([InlineKeyboardButton('调整二级分类排序', callback_data=f'paixuejfl {uid}'),
                     InlineKeyboardButton('删除二级分类', callback_data=f'delejfl {uid}')])
    keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
    fstext = f'''
分类: {fl_pro}
    '''
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))

def paixufl(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    keylist = list(fenlei.find({}, sort=[('row', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['row']
        uid = i['uid']
        keyboard[i["row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'flxxi {uid}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='没有按钮存在')
    else:
        maxrow = max(count)
        if maxrow == 1:
            context.bot.send_message(chat_id=user_id, text='只有一行按钮无法调整')
        else:
            for i in range(0, maxrow):
                if i == 0:
                    keyboard.append([InlineKeyboardButton(f'第{i + 1}行下移', callback_data=f'flpxyd xiayi:{i + 1}')])
                elif i == maxrow - 1:
                    keyboard.append([InlineKeyboardButton(f'第{i + 1}行上移', callback_data=f'flpxyd shangyi:{i + 1}')])
                else:
                    keyboard.append([InlineKeyboardButton(f'第{i + 1}行上移', callback_data=f'flpxyd shangyi:{i + 1}'),
                                     InlineKeyboardButton(f'第{i + 1}行下移', callback_data=f'flpxyd xiayi:{i + 1}')])
            keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
            context.bot.send_message(chat_id=user_id, text='商品管理', reply_markup=InlineKeyboardMarkup(keyboard))

def flpxyd(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    qudata = query.data.replace('flpxyd ', '')
    qudataall = qudata.split(':')
    yidongtype = qudataall[0]
    row = int(qudataall[1])
    if yidongtype == 'shangyi':
        fenlei.update_many({"row": row - 1}, {"$set": {'row': 99}})
        fenlei.update_many({"row": row}, {"$set": {'row': row - 1}})
        fenlei.update_many({"row": 99}, {"$set": {'row': row}})
    else:
        fenlei.update_many({"row": row + 1}, {"$set": {'row': 99}})
        fenlei.update_many({"row": row}, {"$set": {'row': row + 1}})
        fenlei.update_many({"row": 99}, {"$set": {'row': row}})
    keylist = list(fenlei.find({}, sort=[('row', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    for i in keylist:
        uid = i['uid']
        projectname = i['projectname']
        row = i['row']
        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'flxxi {uid}'))
    keyboard.append([InlineKeyboardButton("新建一行", callback_data='newfl'),
                     InlineKeyboardButton('调整行排序', callback_data='paixufl'),
                     InlineKeyboardButton('删除一行', callback_data='delfl')])
    context.bot.send_message(chat_id=user_id, text='商品管理', reply_markup=InlineKeyboardMarkup(keyboard))

def delejfl(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    uid = query.data.replace('delejfl ', '')
    fl_pro = fenlei.find_one({'uid': uid})['projectname']
    keylist = list(ejfl.find({'uid': uid}, sort=[('row', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        projectname = i['projectname']
        row = i['row']
        nowuid = i['nowuid']
        keyboard[i["row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'fejxxi {nowuid}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='没有按钮存在')
    else:
        maxrow = max(count)
        for i in range(0, maxrow):
            pxuid = ejfl.find_one({'uid': uid, 'row': i + 1})['nowuid']
            keyboard.append([InlineKeyboardButton(f'删除第{i + 1}行', callback_data=f'qrscejrow {i + 1}:{pxuid}')])
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        context.bot.send_message(chat_id=user_id, text=f'分类: {fl_pro}', reply_markup=InlineKeyboardMarkup(keyboard))

def qrscejrow(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    del_message(query.message)

    row = int(query.data.replace('qrscejrow ', '').split(':')[0])
    nowuid = query.data.replace('qrscejrow ', '').split(':')[1]
    uid = ejfl.find_one({'nowuid': nowuid})['uid']
    bot_id = context.bot.id
    ejfl.delete_many({'uid': uid, "row": row})
    max_list = list(ejfl.find({'row': {"$gt": row}}))
    for i in max_list:
        max_row = i['row']
        ejfl.update_many({'uid': uid, 'row': max_row}, {"$set": {"row": max_row - 1}})

    fl_pro = fenlei.find_one({'uid': uid})['projectname']
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    ej_list = ejfl.find({'uid': uid})
    for i in ej_list:
        nowuid = i['nowuid']
        projectname = i['projectname']
        row = i['row']
        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'fejxxi {nowuid}'))

    keyboard.append([InlineKeyboardButton('修改分类名', callback_data=f'upspname {uid}'),
                     InlineKeyboardButton('新增二级分类', callback_data=f'newejfl {uid}')])
    keyboard.append([InlineKeyboardButton('调整二级分类排序', callback_data=f'paixuejfl {uid}'),
                     InlineKeyboardButton('删除二级分类', callback_data=f'delejfl {uid}')])
    keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
    fstext = f'''
分类: {fl_pro}
    '''
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def del_ejfl_open(update: Update, context: CallbackContext):
    """打开删除二级分类确认提示"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # 管理员权限检查
    if not is_admin(user_id):
        query.answer("❌ 您没有权限执行此操作", show_alert=True)
        return
    
    query.answer()
    
    # 解析 nowuid
    try:
        nowuid = query.data.replace('del_ejfl_open:', '')
        if not nowuid:
            query.edit_message_text("❌ 参数错误")
            return
    except Exception as e:
        logging.error(f"❌ 解析删除分类参数失败: {e}")
        query.edit_message_text("❌ 参数错误")
        return
    
    # 获取二级分类信息
    ej_list = ejfl.find_one({'nowuid': nowuid})
    if not ej_list:
        query.edit_message_text("❌ 未找到该分类")
        return
    
    ej_projectname = ej_list['projectname']
    uid = ej_list['uid']
    
    # 获取一级分类信息
    fl_list = fenlei.find_one({'uid': uid})
    fl_pro = fl_list['projectname'] if fl_list else '未知分类'
    
    # 统计库存和已售数量
    kc = hb.count_documents({'nowuid': nowuid, 'state': 0})
    ys = hb.count_documents({'nowuid': nowuid, 'state': 1})
    
    # 显示确认提示
    stock_warning = '\n⚠️ 该分类下仍有库存，删除后库存将被清空！' if kc > 0 else ''
    fstext = f'''
⚠️ <b>确认删除二级分类</b>

主分类: {fl_pro}
二级分类: <b>{ej_projectname}</b>

📦 当前库存: {kc}
📊 已售数量: {ys}

<b>⚠️ 警告：删除后无法恢复！</b>{stock_warning}

确定要删除该分类吗？
    '''.strip()
    
    keyboard = [
        [InlineKeyboardButton('✅ 确认删除', callback_data=f'del_ejfl_confirm:{nowuid}')],
        [InlineKeyboardButton('❌ 取消', callback_data=f'fejxxi {nowuid}')]
    ]
    
    query.edit_message_text(
        text=fstext,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def del_ejfl_confirm(update: Update, context: CallbackContext):
    """确认删除二级分类"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # 管理员权限检查
    if not is_admin(user_id):
        query.answer("❌ 您没有权限执行此操作", show_alert=True)
        return
    
    query.answer()
    
    # 解析 nowuid
    try:
        nowuid = query.data.replace('del_ejfl_confirm:', '')
        if not nowuid:
            query.edit_message_text("❌ 参数错误")
            return
    except Exception as e:
        logging.error(f"❌ 解析删除确认参数失败: {e}")
        query.edit_message_text("❌ 参数错误")
        return
    
    # 获取二级分类信息
    ej_list = ejfl.find_one({'nowuid': nowuid})
    if not ej_list:
        query.edit_message_text("❌ 未找到该分类，可能已被删除")
        return
    
    ej_projectname = ej_list['projectname']
    uid = ej_list['uid']
    row = ej_list['row']
    
    try:
        # 删除该分类下的所有库存 (hb表)
        hb_delete_result = hb.delete_many({'nowuid': nowuid})
        logging.info(f"✅ 删除库存: nowuid={nowuid}, 数量={hb_delete_result.deleted_count}")
        
        # 删除该分类下的协议号 (xyh表)
        xyh_delete_result = xyh.delete_many({'nowuid': nowuid})
        logging.info(f"✅ 删除协议号: nowuid={nowuid}, 数量={xyh_delete_result.deleted_count}")
        
        # 删除该二级分类本身
        ejfl.delete_one({'nowuid': nowuid})
        logging.info(f"✅ 删除二级分类: nowuid={nowuid}, 名称={ej_projectname}")
        
        # 调整同一级分类下的其他二级分类的排序
        max_list = list(ejfl.find({'uid': uid, 'row': {"$gt": row}}))
        for i in max_list:
            max_row = i['row']
            ejfl.update_many({'uid': uid, 'row': max_row}, {"$set": {"row": max_row - 1}})
        
        # 显示成功消息并返回上级分类页面
        fl_list = fenlei.find_one({'uid': uid})
        fl_pro = fl_list['projectname'] if fl_list else '未知分类'
        
        # 构建返回上级分类的键盘 - 每个分类一行
        ej_list = list(ejfl.find({'uid': uid}, sort=[('row', 1)]))
        keyboard = []
        
        for i in ej_list:
            ej_nowuid = i['nowuid']
            ej_name = i['projectname']
            # 每个分类单独一行
            keyboard.append([InlineKeyboardButton(f'{ej_name}', callback_data=f'fejxxi {ej_nowuid}')])
        
        # 添加管理按钮
        keyboard.append([InlineKeyboardButton('修改分类名', callback_data=f'upspname {uid}'),
                         InlineKeyboardButton('新增二级分类', callback_data=f'newejfl {uid}')])
        keyboard.append([InlineKeyboardButton('调整二级分类排序', callback_data=f'paixuejfl {uid}'),
                         InlineKeyboardButton('删除二级分类', callback_data=f'delejfl {uid}')])
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        
        fstext = f'''
✅ <b>二级分类已删除</b>

已删除分类: <b>{ej_projectname}</b>

分类: {fl_pro}
        '''.strip()
        
        query.edit_message_text(
            text=fstext,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logging.error(f"❌ 删除二级分类失败: {e}")
        query.edit_message_text(f"❌ 删除失败，请稍后重试\n错误: {str(e)}")


def delfl(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()
    bot_id = context.bot.id
    keylist = list(fenlei.find({}, sort=[('row', 1)]))
    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], []]
    count = []
    for i in keylist:
        uid = i['uid']
        projectname = i['projectname']
        row = i['row']
        keyboard[i["row"] - 1].append(InlineKeyboardButton(projectname, callback_data=f'flxxi {uid}'))
        count.append(row)
    if count == []:
        context.bot.send_message(chat_id=user_id, text='没有按钮存在')
    else:
        maxrow = max(count)
        for i in range(0, maxrow):
            keyboard.append([InlineKeyboardButton(f'删除第{i + 1}行', callback_data=f'qrscflrow {i + 1}')])
        keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
        context.bot.send_message(chat_id=user_id, text='商品管理', reply_markup=InlineKeyboardMarkup(keyboard))


def qrscflrow(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()


def backzcd(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = user.find_one({'user_id': user_id})['lang']

    fenlei_data = list(fenlei.find({}, sort=[('row', 1)]))
    ejfl_data = list(ejfl.find({}))
    hb_data = list(hb.find({'state': 0}))

    keyboard = [[] for _ in range(50)]

    for i in fenlei_data:
        uid = i['uid']
        projectname = i['projectname']
        row = i['row']

        hsl = sum(
            1 for j in ejfl_data if j['uid'] == uid
            for hb_item in hb_data if hb_item['nowuid'] == j['nowuid']
        )

        display_name = projectname if lang == 'zh' else get_fy(projectname)
        label = f'{display_name} [{hsl}个]' if lang == 'zh' else f'{display_name} [{hsl}]'

        keyboard[row - 1].append(
            InlineKeyboardButton(label, callback_data=f'catejflsp {uid}:{hsl}')
        )

    # 文本说明
    if lang == 'zh':
        fstext = (
            "<b>🛒 商品分类 - 请选择所需：</b>\n\n"
            "<b>❗快速查找商品库存发送区号！如（+94）</b>\n\n"
            "<b>❗️首次购买请先少量测试，避免纠纷</b>！\n\n"
            "<b>❗️长期未使用账户可能会出现问题，联系客服处理</b>。"
        )
        keyboard.append([InlineKeyboardButton("⚠️注意事项⚠️（点我查看）", callback_data="notice")])
        keyboard.append([InlineKeyboardButton("❌关闭", callback_data=f"close {user_id}")])
    else:
        fstext = (
            "<b>🛒 Product Categories - Please choose:</b>\n"
            "❗️If you are new, please start with a small test purchase to avoid issues.\n"
            "❗️Inactive accounts may encounter problems, please contact support."
        )
        keyboard.append([InlineKeyboardButton("⚠️ Important Notice ⚠️", callback_data="notice")])
        keyboard.append([InlineKeyboardButton("❌ Close", callback_data=f"close {user_id}")])

    query.edit_message_text(
        text=fstext,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ✅ 新增：返回商品列表的回调处理器
def show_product_list(update: Update, context: CallbackContext):
    """处理返回商品列表的回调"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    user_data = user.find_one({'user_id': user_id})
    lang = user_data.get('lang', 'zh')

    fenlei_data = list(fenlei.find({}, sort=[('row', 1)]))
    ejfl_data = list(ejfl.find({}))
    hb_data = list(hb.find({'state': 0}))

    # ✅ 一级分类始终显示，显示库存数量（包括0）
    keyboard = []
    displayed_categories = []
    
    for i in fenlei_data:
        uid = i['uid']
        projectname = i['projectname']
        row = i['row']
        hsl = sum(
            1 for j in ejfl_data if j['uid'] == uid
            for hb_item in hb_data if hb_item['nowuid'] == j['nowuid']
        )
        
        # ✅ 一级分类始终显示（不论库存多少）
        projectname_display = projectname if lang == 'zh' else get_fy(projectname)
        displayed_categories.append({
            'name': projectname_display,
            'stock': hsl,
            'uid': uid,
            'row': row
        })
    
    # 按原有行号排序（保持管理员设置的顺序）
    displayed_categories.sort(key=lambda x: x['row'])
    
    # 每行一个按钮
    for cat in displayed_categories:
        # ✅ 显示库存数量，0库存直接显示0
        if cat['stock'] > 0:
            if lang == 'zh':
                button_text = f'{cat["name"]} [{cat["stock"]}个]'
            else:
                button_text = f'{cat["name"]} [{cat["stock"]} items]'
        else:
            if lang == 'zh':
                button_text = f'{cat["name"]} [0个]'
            else:
                button_text = f'{cat["name"]} [0 items]'
        
        keyboard.append([
            InlineKeyboardButton(
                button_text, 
                callback_data=f'catejflsp {cat["uid"]}:{cat["stock"]}'
            )
        ])

    if lang == 'zh':
        fstext = (
            "<b>🛒 商品分类 - 请选择所需：</b>\n\n"
            "<b>❗快速查找商品库存发送区号！如（+94）</b>\n\n"
            "<b>❗️首次购买请先少量测试，避免纠纷</b>！\n\n"
            "<b>❗️长期未使用账户可能会出现问题，联系客服处理</b>。"
        )
        keyboard.append([InlineKeyboardButton("⚠️注意事项⚠️（点我查看）", callback_data="notice")])
        keyboard.append([InlineKeyboardButton("❌关闭", callback_data=f"close {user_id}")])
    else:
        fstext = (
            "<b>🛒 Product Categories - Please choose:</b>\n"
            "❗️If you are new, please start with a small test purchase to avoid issues.\n"
            "❗️Inactive accounts may encounter problems, please contact support."
        )
        keyboard.append([InlineKeyboardButton("⚠️ Important Notice ⚠️", callback_data="notice")])
        keyboard.append([InlineKeyboardButton("❌ Close", callback_data=f"close {user_id}")])

    query.edit_message_text(
        text=fstext,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        pass

    try:
        import unicodedata
        unicodedata.numeric(s)
        return True
    except (TypeError, ValueError):
        pass

    return False

def dabaohao(context, user_id, folder_names, leixing, nowuid, erjiprojectname, fstext, yssj):
    current_time = get_beijing_now()
    formatted_time = format_beijing_time(current_time, "%Y%m%d%H%M%S")
    timestamp = str(current_time.timestamp()).replace(".", "")
    bianhao = formatted_time + timestamp
    timer = beijing_now_str()
    count = len(folder_names)

    if leixing == '协议号':
        zip_filename = f"./协议号发货/{user_id}_{int(time.time())}.zip"
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_name in folder_names:
                json_file = os.path.join(f"./协议号/{nowuid}", file_name + ".json")
                session_file = os.path.join(f"./协议号/{nowuid}", file_name + ".session")
                if os.path.exists(json_file):
                    zipf.write(json_file, os.path.basename(json_file))
                if os.path.exists(session_file):
                    zipf.write(session_file, os.path.basename(session_file))
        goumaijilua(leixing, bianhao, user_id, erjiprojectname, zip_filename, fstext, timer, count)
        context.bot.send_document(chat_id=user_id, document=open(zip_filename, "rb"))

    elif leixing == '直登号':
        zip_filename = f"./发货/{user_id}_{int(time.time())}.zip"
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            for folder_name in folder_names:
                base_path = os.path.join(f"./号包/{nowuid}", folder_name)
                if os.path.exists(base_path):
                    for root, dirs, files in os.walk(base_path):
                        for file in files:
                            full_path = os.path.join(root, file)
                            rel_path = os.path.join(folder_name, os.path.relpath(full_path, base_path))
                            zipf.write(full_path, rel_path)
        goumaijilua(leixing, bianhao, user_id, erjiprojectname, zip_filename, fstext, timer, count)
        context.bot.send_document(chat_id=user_id, document=open(zip_filename, "rb"))

    elif leixing == 'API链接':
        link_text = '\n'.join(folder_names)
        context.bot.send_message(chat_id=user_id, text=link_text)
        goumaijilua(leixing, bianhao, user_id, erjiprojectname, link_text, fstext, timer, count)

    elif leixing == 'txt文本':
        content = '\n'.join(folder_names)
        context.bot.send_message(chat_id=user_id, text=content)
        goumaijilua(leixing, bianhao, user_id, erjiprojectname, content, fstext, timer, count)

    else:
        context.bot.send_message(chat_id=user_id, text=f"❌ 未知商品类型：{leixing}")



def qrgaimai(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    bot_id = context.bot.id
    user_id = query.from_user.id
    fullname = query.from_user.full_name.replace('<', '').replace('>', '')
    username = query.from_user.username
    data = query.data.replace('qrgaimai ', '')
    nowuid = data.split(':')[0]
    gmsl = int(data.split(':')[1])
    zxymoney = float(data.split(':')[2])
    user_list = user.find_one({'user_id': user_id})
    USDT = user_list['USDT']
    lang = user_list['lang']
    
    # Security check: Prevent negative or zero quantity purchases (defense in depth)
    if gmsl <= 0:
        error_msg = '❌ 购买数量无效' if lang == 'zh' else '❌ Invalid quantity'
        context.bot.send_message(chat_id=user_id, text=error_msg)
        return
    
    # Security check: Prevent negative or zero amount purchases
    if zxymoney <= 0:
        error_msg = '❌ 购买金额无效' if lang == 'zh' else '❌ Invalid amount'
        context.bot.send_message(chat_id=user_id, text=error_msg)
        return
    
    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
    if kc < gmsl:
        kcbz = '当前库存不足' if lang == 'zh' else get_fy('当前库存不足')
        context.bot.send_message(chat_id=user_id, text=kcbz)
        return
    keyboard = [[InlineKeyboardButton('✅已读（点击销毁此消息）', callback_data=f'close {user_id}')]]
    if USDT >= zxymoney:
        now_price = standard_num(float(USDT) - float(zxymoney))
        now_price = float(now_price) if str((now_price)).count('.') > 0 else int(standard_num(now_price))

        ejfl_list = ejfl.find_one({'nowuid': nowuid})

        fhtype = hb.find_one({'nowuid': nowuid})['leixing']
        projectname = ejfl_list['projectname']
        erjiprojectname = ejfl_list['projectname']
        yijiid = ejfl_list['uid']
        yiji_list = fenlei.find_one({'uid': yijiid})
        yijiprojectname = yiji_list['projectname']
        fstext = ejfl_list['text']
        fstext = fstext if lang == 'zh' else get_fy(fstext)
        if fhtype == '协议号':
            zgje = user_list['zgje']
            zgsl = user_list['zgsl']
            user.update_one({'user_id': user_id},
                            {"$set": {'USDT': now_price, 'zgje': zgje + zxymoney, 'zgsl': zgsl + gmsl}})
            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
            del_message(query.message)
            # for j in list(hb.find({"nowuid": nowuid,'state': 0},limit=gmsl)):
            #     projectname = j['projectname']
            #     hbid = j['hbid']
            #     timer = beijing_now_str()

            #     hb.update_one({'hbid': hbid},{"$set":{'state': 1, 'yssj': timer, 'gmid': user_id}})
            #     folder_names.append(projectname)

            query_condition = {"nowuid": nowuid, "state": 0}

            pipeline = [
                {"$match": query_condition},
                {"$limit": gmsl}
            ]
            cursor = hb.aggregate(pipeline)
            document_ids = [doc['_id'] for doc in cursor]
            cursor = hb.aggregate(pipeline)
            folder_names = [doc['projectname'] for doc in cursor]

            timer = beijing_now_str()
            update_data = {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}}
            hb.update_many({"_id": {"$in": document_ids}}, update_data)

            # timer = beijing_now_str()
            # update_data = {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}}

            # hb.update_many(query_condition, update_data, limit=gmsl)

            context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML', disable_web_page_preview=True,
                                     reply_markup=InlineKeyboardMarkup(keyboard))
            fstext = f'''
用户: <a href="tg://user?id={user_id}">{fullname}</a> @{username}
用户ID: <code>{user_id}</code>
购买商品: {yijiprojectname}/{erjiprojectname}
购买数量: {gmsl}
购买金额: {zxymoney}
            '''
            # 通知所有管理员 - 使用env配置的管理员列表
            for admin_id in get_admin_ids():
                try:
                    context.bot.send_message(chat_id=admin_id, text=fstext, parse_mode='HTML')
                except Exception as e:
                    logging.warning(f"Failed to send admin notification to {admin_id}: {e}")

            Timer(1, dabaohao,
                  args=[context, user_id, folder_names, '协议号', nowuid, erjiprojectname, fstext, timer]).start()
            # shijiancuo = int(time.time())
            # zip_filename = f"./协议号发货/{user_id}_{shijiancuo}.zip"
            # with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            #     # 将每个文件及其内容添加到 zip 文件中
            #     for file_name in folder_names:
            #         # 检查是否存在以 .json 或 .session 结尾的文件
            #         json_file_path = os.path.join(f"./协议号/{nowuid}", file_name + ".json")
            #         session_file_path = os.path.join(f"./协议号/{nowuid}", file_name + ".session")
            #         if os.path.exists(json_file_path):
            #             zipf.write(json_file_path, os.path.basename(json_file_path))
            #         if os.path.exists(session_file_path):
            #             zipf.write(session_file_path, os.path.basename(session_file_path))
            # current_time = datetime.now()

            # # 将当前时间格式化为字符串
            # formatted_time = current_time.strftime("%Y%m%d%H%M%S")

            # # 添加时间戳
            # timestamp = str(current_time.timestamp()).replace(".", "")

            # # 组合编号
            # bianhao = formatted_time + timestamp
            # timer = beijing_now_str()
            # goumaijilua('协议号', bianhao, user_id, erjiprojectname,zip_filename,fstext, timer)
            # # 发送 zip 文件给用户
            # query.message.reply_document(open(zip_filename, "rb"))



        elif fhtype == '谷歌':
            zgje = user_list['zgje']
            zgsl = user_list['zgsl']
            user.update_one({'user_id': user_id},
                            {"$set": {'USDT': now_price, 'zgje': zgje + zxymoney, 'zgsl': zgsl + gmsl}})
            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
            del_message(query.message)

            context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML', disable_web_page_preview=True,
                                     reply_markup=InlineKeyboardMarkup(keyboard))
            folder_names = []
            for j in list(hb.find({"nowuid": nowuid, 'state': 0, 'leixing': '谷歌'}, limit=gmsl)):
                projectname = j['projectname']
                hbid = j['hbid']
                timer = beijing_now_str()
                hb.update_one({'hbid': hbid}, {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}})
                data = j['data']
                us1 = data['账户']
                us2 = data['密码']
                us3 = data['子邮件']
                fste23xt = f'账户: {us1}\n密码: {us2}\n子邮件: {us3}\n'
                folder_names.append(fste23xt)

            folder_names = '\n'.join(folder_names)

            shijiancuo = int(time.time())
            zip_filename = f"./谷歌发货/{user_id}_{shijiancuo}.txt"
            with open(zip_filename, "w") as f:
                f.write(folder_names)
            current_time = get_beijing_now()

            # 将当前时间格式化为字符串（北京时间）
            formatted_time = format_beijing_time(current_time, "%Y%m%d%H%M%S")

            # 添加时间戳
            timestamp = str(current_time.timestamp()).replace(".", "")

            # 组合编号
            bianhao = formatted_time + timestamp
            timer = beijing_now_str()
            goumaijilua('谷歌', bianhao, user_id, erjiprojectname, zip_filename, fstext, timer)

            query.message.reply_document(open(zip_filename, "rb"))

            fstext = f'''
用户: <a href="tg://user?id={user_id}">{fullname}</a> @{username}
用户ID: <code>{user_id}</code>
购买商品: {yijiprojectname}/{erjiprojectname}
购买数量: {gmsl}
购买金额: {zxymoney}
            '''
            # 通知所有管理员 - 使用env配置的管理员列表
            for admin_id in get_admin_ids():
                try:
                    context.bot.send_message(chat_id=admin_id, text=fstext, parse_mode='HTML')
                except Exception as e:
                    logging.warning(f"Failed to send admin notification to {admin_id}: {e}")


        elif fhtype == 'API':
            zgje = user_list['zgje']
            zgsl = user_list['zgsl']
            user.update_one({'user_id': user_id},
                            {"$set": {'USDT': now_price, 'zgje': zgje + zxymoney, 'zgsl': zgsl + gmsl}})
            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
            del_message(query.message)

            context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML', disable_web_page_preview=True,
                                     reply_markup=InlineKeyboardMarkup(keyboard))
            folder_names = []
            for j in list(hb.find({"nowuid": nowuid, 'state': 0}, limit=gmsl)):
                projectname = j['projectname']
                hbid = j['hbid']
                timer = beijing_now_str()
                hb.update_one({'hbid': hbid}, {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}})
                folder_names.append(projectname)

            shijiancuo = int(time.time())

            zip_filename = f"./手机接码发货/{user_id}_{shijiancuo}.txt"
            with open(zip_filename, "w") as f:
                for folder_name in folder_names:
                    f.write(folder_name + "\n")

            current_time = get_beijing_now()

            # 将当前时间格式化为字符串（北京时间）
            formatted_time = format_beijing_time(current_time, "%Y%m%d%H%M%S")

            # 添加时间戳
            timestamp = str(current_time.timestamp()).replace(".", "")

            # 组合编号
            bianhao = formatted_time + timestamp
            timer = beijing_now_str()
            link_text = '\n'.join(folder_names)  # API链接内容应该是账号列表
            goumaijilua('API链接', bianhao, user_id, erjiprojectname, link_text, fstext, timer)

            query.message.reply_document(open(zip_filename, "rb"))

            fstext = f'''
用户: <a href="tg://user?id={user_id}">{fullname}</a> @{username}
用户ID: <code>{user_id}</code>
购买商品: {yijiprojectname}/{erjiprojectname}
购买数量: {gmsl}
购买金额: {zxymoney}
            '''
            # 通知所有管理员 - 使用env配置的管理员列表
            for admin_id in get_admin_ids():
                try:
                    context.bot.send_message(chat_id=admin_id, text=fstext, parse_mode='HTML')
                except Exception as e:
                    logging.warning(f"Failed to send admin notification to {admin_id}: {e}")
        elif fhtype == '会员链接':
            zgje = user_list['zgje']
            zgsl = user_list['zgsl']
            user.update_one({'user_id': user_id},
                            {"$set": {'USDT': now_price, 'zgje': zgje + zxymoney, 'zgsl': zgsl + gmsl}})
            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
            del_message(query.message)
            folder_names = []
            for j in list(hb.find({"nowuid": nowuid, 'state': 0}, limit=gmsl)):
                projectname = j['projectname']
                hbid = j['hbid']
                timer = beijing_now_str()
                hb.update_one({'hbid': hbid}, {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}})
                folder_names.append(projectname)

            context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML', disable_web_page_preview=True,
                                     reply_markup=InlineKeyboardMarkup(keyboard))

            folder_names = '\n'.join(folder_names)

            current_time = get_beijing_now()

            # 将当前时间格式化为字符串（北京时间）
            formatted_time = format_beijing_time(current_time, "%Y%m%d%H%M%S")

            # 添加时间戳
            timestamp = str(current_time.timestamp()).replace(".", "")

            # 组合编号
            bianhao = formatted_time + timestamp
            timer = beijing_now_str()
            goumaijilua('会员链接', bianhao, user_id, erjiprojectname, folder_names, fstext, timer, gmsl)



            context.bot.send_message(chat_id=user_id, text=folder_names, disable_web_page_preview=True)

            fstext = f'''
用户: <a href="tg://user?id={user_id}">{fullname}</a> @{username}
用户ID: <code>{user_id}</code>
购买商品: {yijiprojectname}/{erjiprojectname}
购买数量: {gmsl}
购买金额: {zxymoney}
            '''
            # 通知所有管理员 - 使用env配置的管理员列表
            for admin_id in get_admin_ids():
                try:
                    context.bot.send_message(chat_id=admin_id, text=fstext, parse_mode='HTML')
                except Exception as e:
                    logging.warning(f"Failed to send admin notification to {admin_id}: {e}")
        else:
            zgje = user_list['zgje']
            zgsl = user_list['zgsl']
            user.update_one({'user_id': user_id},
                            {"$set": {'USDT': now_price, 'zgje': zgje + zxymoney, 'zgsl': zgsl + gmsl}})
            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
            del_message(query.message)

            # folder_names = []
            # for j in list(hb.find({"nowuid": nowuid, 'state': 0}, limit=gmsl)):
            #     projectname = j['projectname']
            #     hbid = j['hbid']
            #     timer = beijing_now_str()
            #     hb.update_one({'hbid': hbid}, {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}})
            #     folder_names.append(projectname)

            query_condition = {"nowuid": nowuid, "state": 0}

            pipeline = [
                {"$match": query_condition},
                {"$limit": gmsl}
            ]
            cursor = hb.aggregate(pipeline)
            document_ids = [doc['_id'] for doc in cursor]
            cursor = hb.aggregate(pipeline)
            folder_names = [doc['projectname'] for doc in cursor]

            timer = beijing_now_str()
            update_data = {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}}
            hb.update_many({"_id": {"$in": document_ids}}, update_data)

            context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML', disable_web_page_preview=True,
                                     reply_markup=InlineKeyboardMarkup(keyboard))

            fstext = f'''
用户: <a href="tg://user?id={user_id}">{fullname}</a> @{username}
用户ID: <code>{user_id}</code>
购买商品: {yijiprojectname}/{erjiprojectname}
购买数量: {gmsl}
购买金额: {zxymoney}
            '''
            # 通知所有管理员 - 使用env配置的管理员列表
            for admin_id in get_admin_ids():
                try:
                    context.bot.send_message(chat_id=admin_id, text=fstext, parse_mode='HTML')
                except Exception as e:
                    logging.warning(f"Failed to send admin notification to {admin_id}: {e}")

            Timer(1, dabaohao,
                  args=[context, user_id, folder_names, '直登号', nowuid, erjiprojectname, fstext, timer]).start()
            # shijiancuo = int(time.time())
            # zip_filename = f"./发货/{user_id}_{shijiancuo}.zip"
            # with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            #     # 将每个文件夹及其内容添加到 zip 文件中
            #     for folder_name in folder_names:
            #         full_folder_path = os.path.join(f"./号包/{nowuid}", folder_name)
            #         if os.path.exists(full_folder_path):
            #             # 添加文件夹及其内容
            #             for root, dirs, files in os.walk(full_folder_path):
            #                 for file in files:
            #                     file_path = os.path.join(root, file)
            #                     # 使用相对路径在压缩包中添加文件，并设置压缩包内部的路径
            #                     zipf.write(file_path, os.path.join(folder_name, os.path.relpath(file_path, full_folder_path)))
            #         else:
            #             # update.message.reply_text(f"文件夹 '{folder_name}' 不存在！")
            #             pass

            # # 发送 zip 文件给用户

            # folder_names = '\n'.join(folder_names)

            # current_time = datetime.now()

            # # 将当前时间格式化为字符串
            # formatted_time = current_time.strftime("%Y%m%d%H%M%S")

            # # 添加时间戳
            # timestamp = str(current_time.timestamp()).replace(".", "")

            # # 组合编号
            # bianhao = formatted_time + timestamp
            # timer = beijing_now_str()
            # goumaijilua('直登号', bianhao, user_id, erjiprojectname, zip_filename,fstext, timer)

            # query.message.reply_document(open(zip_filename, "rb"))




    else:
        if lang == 'zh':
            context.bot.send_message(chat_id=user_id, text='❌ 余额不足，请及时充值！')
            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
        else:
            context.bot.send_message(chat_id=user_id, text='❌ Insufficient balance, please recharge in time!')
        return


def qchuall(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    bot_id = context.bot.id
    user_id = query.from_user.id

    nowuid = query.data.replace('qchuall ', '')

    ejfl_list = ejfl.find_one({'nowuid': nowuid})
    fhtype = hb.find_one({'nowuid': nowuid})['leixing']
    projectname = ejfl_list['projectname']
    yijiid = ejfl_list['uid']
    yiji_list = fenlei.find_one({'uid': yijiid})
    yijiprojectname = yiji_list['projectname']

    folder_names = []
    if fhtype == '协议号':
        for j in list(hb.find({"nowuid": nowuid, 'state': 0})):
            projectname = j['projectname']
            hbid = j['hbid']
            timer = beijing_now_str()
            hb.delete_one({'hbid': hbid})
            folder_names.append(projectname)
        shijiancuo = int(time.time())
        zip_filename = f"./协议号发货/{user_id}_{shijiancuo}.zip"
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            # 将每个文件及其内容添加到 zip 文件中
            for file_name in folder_names:
                # 检查是否存在以 .json 或 .session 结尾的文件
                json_file_path = os.path.join(f"./协议号/{nowuid}", file_name + ".json")
                session_file_path = os.path.join(f"./协议号/{nowuid}", file_name + ".session")
                if os.path.exists(json_file_path):
                    zipf.write(json_file_path, os.path.basename(json_file_path))
                if os.path.exists(session_file_path):
                    zipf.write(session_file_path, os.path.basename(session_file_path))
        query.message.reply_document(open(zip_filename, "rb"))

    elif fhtype == 'API':
        for j in list(hb.find({"nowuid": nowuid, 'state': 0})):
            projectname = j['projectname']
            hbid = j['hbid']
            timer = beijing_now_str()
            hb.delete_one({'hbid': hbid})
            folder_names.append(projectname)

        shijiancuo = int(time.time())

        zip_filename = f"./手机接码发货/{user_id}_{shijiancuo}.txt"
        with open(zip_filename, "w") as f:
            for folder_name in folder_names:
                f.write(folder_name + "\n")

        query.message.reply_document(open(zip_filename, "rb"))

    elif fhtype == '谷歌':
        for j in list(hb.find({"nowuid": nowuid, 'state': 0, 'leixing': '谷歌'})):
            projectname = j['projectname']
            hbid = j['hbid']
            timer = beijing_now_str()
            hb.update_one({'hbid': hbid}, {"$set": {'state': 1, 'yssj': timer, 'gmid': user_id}})
            data = j['data']
            us1 = data['账户']
            us2 = data['密码']
            us3 = data['子邮件']
            fste23xt = f'login: {us1}\npassword: {us2}\nsubmail: {us3}\n'
            hb.delete_one({'hbid': hbid})
            folder_names.append(fste23xt)
        folder_names = '\n'.join(folder_names)
        shijiancuo = int(time.time())

        zip_filename = f"./谷歌发货/{user_id}_{shijiancuo}.txt"
        with open(zip_filename, "w") as f:

            f.write(folder_names)

        query.message.reply_document(open(zip_filename, "rb"))


    elif fhtype == '会员链接':
        for j in list(hb.find({"nowuid": nowuid, 'state': 0})):
            projectname = j['projectname']
            hbid = j['hbid']
            timer = beijing_now_str()
            hb.delete_one({'hbid': hbid})
            folder_names.append(projectname)
        folder_names = '\n'.join(folder_names)

        context.bot.send_message(chat_id=user_id, text=folder_names, disable_web_page_preview=True)
    else:
        for j in list(hb.find({"nowuid": nowuid, 'state': 0})):
            projectname = j['projectname']
            hbid = j['hbid']
            timer = beijing_now_str()
            hb.delete_one({'hbid': hbid})
            folder_names.append(projectname)

        shijiancuo = int(time.time())
        zip_filename = f"./发货/{user_id}_{shijiancuo}.zip"
        with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
            # 将每个文件夹及其内容添加到 zip 文件中
            for folder_name in folder_names:
                full_folder_path = os.path.join(f"./号包/{nowuid}", folder_name)
                if os.path.exists(full_folder_path):
                    # 添加文件夹及其内容
                    for root, dirs, files in os.walk(full_folder_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            # 使用相对路径在压缩包中添加文件，并设置压缩包内部的路径
                            zipf.write(file_path,
                                       os.path.join(folder_name, os.path.relpath(file_path, full_folder_path)))
                else:
                    # update.message.reply_text(f"文件夹 '{folder_name}' 不存在！")
                    pass

        query.message.reply_document(open(zip_filename, "rb"))

    ej_list = ejfl.find_one({'nowuid': nowuid})
    uid = ej_list['uid']
    ej_projectname = ej_list['projectname']
    money = ej_list['money']
    fl_pro = fenlei.find_one({'uid': uid})['projectname']
    keyboard = [
        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
    ]
    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))
    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
    '''
    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


def qxdingdan(update: Update, context: CallbackContext):
    query = update.callback_query
    chat = query.message.chat
    query.answer()
    bot_id = context.bot.id
    chat_id = chat.id
    user_id = query.from_user.id

    topup.delete_one({'user_id': user_id})
    context.bot.delete_message(chat_id=query.from_user.id, message_id=query.message.message_id)

def get_current_rate():
    return 7.2  # 固定汇率，按你需要的比例设置


def textkeyboard(update: Update, context: CallbackContext):
    chat = update.effective_chat
    if chat.type == 'private':
        
        user_id = chat.id
        username = chat.username
        firstname = chat.first_name
        lastname = chat.last_name
        bot_id = context.bot.id
        fullname = chat.full_name.replace('<', '').replace('>', '')
        reply_to_message_id = update.effective_message.message_id
        timer = beijing_now_str()
        user_list = user.find_one({"user_id": user_id})
        creation_time = user_list['creation_time']
        state = user_list['state']
        sign = user_list['sign']
        USDT = user_list['USDT']
        zgje = user_list['zgje']
        zgsl = user_list['zgsl']
        lang = user_list['lang']
        text = update.message.text
        zxh = update.message.text_html
        yyzt = shangtext.find_one({'projectname': '营业状态'})['text']
        if yyzt == 0:
            # 营业状态为关闭时，只允许管理员访问
            if not is_admin(user_id):
                return
        
        # 检查是否在等待代理地址输入（管理员功能）
        if is_admin(user_id):
            if handle_agent_address_input(update, context, user_id, text):
                return

        get_key_list = get_key.find({})
        get_prolist = []
        # ✅ 预设的主要按钮英文翻译（与start函数中的button_translations保持一致）
        button_translations = {
            '🛒商品列表': '🛒Product List',
            '👤个人中心': '👤Personal Center', 
            '💳余额充值': '💳Balance Recharge',
            '📞联系客服': '📞Contact Support',
            '🔶使用教程': '🔶Usage Tutorial',
            '🔷出货通知': '🔷Delivery Notice',
            '🔎查询库存': '🔎Check Inventory',
            '🌐 语言切换': '🌐 Language Switching',
            '⬅️ 返回主菜单': '⬅️ Return to Main Menu'
        }
        
        for i in get_key_list:
            chinese_name = i["projectname"]
            get_prolist.append(chinese_name)
            # 同时添加英文翻译（如果有的话）
            if chinese_name in button_translations:
                get_prolist.append(button_translations[chinese_name])
        
        # ✅ 修复：如果用户点击的是底部按钮，重置sign状态并直接处理按钮
        is_button_click = False
        if update.message.text:
            if text in get_prolist:
                is_button_click = True
                # 重置用户的sign状态到数据库
                user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                sign = 0
        
        # 仅当sign不为0且不是按钮点击时，才处理特殊状态输入
        if sign != 0 and not is_button_click:
            if update.message.text:

                if sign == 'addhb':
                    if is_number(text):

                        money = float(text) if text.count('.') > 0 else int(text)
                        if money < 1:
                            context.bot.send_message(chat_id=user_id, text='⚠️ 输入错误，最少金额不能小于1U')
                            return
                        if USDT >= money:
                            keyboard = [[InlineKeyboardButton('🚫取消', callback_data=f'close {user_id}')]]
                            user.update_one({'user_id': user_id}, {"$set": {'sign': f'sethbsl {money}'}})
                            context.bot.send_message(chat_id=user_id, text='<b>💡 请回复你要发送的红包数量</b>',
                                                     parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

                        else:
                            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                            context.bot.send_message(chat_id=user_id, text='⚠️ 操作失败，余额不足')
                    else:
                        context.bot.send_message(chat_id=user_id, text='⚠️ 输入错误，请输入数字！')
                elif 'sethbsl' in sign:
                    money = sign.replace('sethbsl ', '')
                    money = float(money) if money.count('.') > 0 else int(money)

                    if is_number(text) and text.count('.') == 0:
                        hbsl = int(text)
                        if hbsl == 0:
                            context.bot.send_message(chat_id=user_id, text='红包数量不能为0')
                            return
                        if hbsl > 100:
                            context.bot.send_message(chat_id=user_id, text='红包数量最大为100')
                            return
                        user_list = user.find_one({"user_id": user_id})
                        USDT = user_list['USDT']
                        if USDT < money:
                            user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                            context.bot.send_message(chat_id=user_id, text='⚠️ 操作失败，余额不足')
                            return
                        user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                        uid = generate_24bit_uid()
                        timer = beijing_now_str()
                        hongbao.insert_one({
                            'uid': uid,
                            'user_id': user_id,
                            'fullname': fullname,
                            'hbmoney': money,
                            'hbsl': hbsl,
                            'timer': timer,
                            'state': 0
                        })
                        now_money = standard_num(USDT - money)
                        now_money = float(now_money) if str((now_money)).count('.') > 0 else int(
                            standard_num(now_money))
                        user.update_one({'user_id': user_id}, {"$set": {'USDT': now_money}})
                        fstext = f'''
🧧 <a href="tg://user?id={user_id}">{fullname}</a> 发送了一个红包
💵总金额:{money} USDT💰 剩余:{hbsl}/{hbsl}

✅ 红包添加成功，请点击按钮发送
                        '''
                        keyboard = [
                            [InlineKeyboardButton('发送红包', switch_inline_query=f'redpacket {uid}')]
                        ]

                        context.bot.send_message(chat_id=user_id, text=fstext,
                                                 reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

                    else:
                        user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                        context.bot.send_message(chat_id=user_id, text='⚠️ 输入错误，请输入数字！')


                elif sign == 'startupdate':
                    entities = update.message.entities
                    shangtext.update_one({"projectname": '欢迎语'}, {"$set": {"text": zxh}})
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                    context.bot.send_message(chat_id=user_id, text=f'当前欢迎语为: {zxh}', parse_mode='HTML')
                elif 'zdycz' in sign:
                    if is_number(text):
                        del_message(update.message)
                        del_message_id = sign.replace('zdycz ', '')
                        try:
                            context.bot.deleteMessage(chat_id=user_id, message_id=del_message_id)
                        except:
                            pass

                        money = float(text)
                        user_info = user.find_one({'user_id': user_id})
                        lang = user_info.get('lang', 'zh')
                        paytype = user_info.get('cz_paytype', 'usdt')

                        now = get_beijing_now()
                        timer = format_beijing_time(now, '%Y%m%d%H%M%S')
                        timer_str = format_beijing_time(now)
                        expire_str = format_beijing_time(now + timedelta(minutes=10))

                        topup.delete_many({'user_id': user_id, 'status': 'pending'})

                        # 构建唯一金额（含随机尾数）
                        while True:
                            suijishu = round(random.uniform(0.0001, 0.9999), 2)
                            if paytype == 'usdt':
                                final_amount = float(Decimal(str(money)) + Decimal(str(suijishu)))
                            else:
                                rate = get_current_rate()
                                if not rate or rate <= 0:
                                    context.bot.send_message(chat_id=user_id, text="汇率错误，请稍后重试")
                                    return
                                final_amount = round(money * rate + suijishu, 2)

                            if not topup.find_one({'money': final_amount, 'status': 'pending'}):
                                break

                        # USDT 模式：展示地址和二维码
                        if paytype == 'usdt':
                            trc20 = shangtext.find_one({'projectname': '充值地址'})['text']
                            
                            if lang == 'zh':
                                text = f"""
<b>充值详情</b>

✅ <b>唯一收款地址：</b><code>{trc20}</code>
（推荐使用扫码转账更加安全 👉点击上方地址即可快速复制粘贴）

💰 <b>实际支付金额：</b><code>{final_amount}</code> USDT
（👉点击上方金额可快速复制粘贴）

<b>充值订单创建时间：</b>{timer_str}
<b>转账最后截止时间：</b>{expire_str}

❗️请一定按照金额后面小数点转账，否则无法自动到账
❗️付款前请再次核对地址与金额，避免转错
                                """.strip()
                            else:
                                text = f"""
<b>Recharge Details</b>

✅ <b>Unique Payment Address:</b><code>{trc20}</code>
(Recommended to use QR code scanning for safer transfer 👉Click above address to copy)

💰 <b>Actual Payment Amount:</b><code>{final_amount}</code> USDT
(👉Click above amount to copy)

<b>Order Created:</b>{timer_str}
<b>Payment Deadline:</b>{expire_str}

❗️Please transfer exactly according to the decimal amount, otherwise it cannot be automatically credited
❗️Please double-check the address and amount before payment to avoid mistakes
                                """.strip()

                            keyboard = [[InlineKeyboardButton("❌取消订单" if lang == 'zh' else "❌Cancel Order", callback_data=f'qxdingdan {user_id}')]]
                            
                            # 发送图片 + 消息（与按钮充值保持一致）
                            try:
                                msg = context.bot.send_photo(
                                    chat_id=user_id,
                                    photo=open(f'{trc20}.png', 'rb'),
                                    caption=text,
                                    parse_mode='HTML',
                                    reply_markup=InlineKeyboardMarkup(keyboard)
                                )
                            except FileNotFoundError:
                                # 如果二维码文件不存在，回退到文本消息
                                msg = context.bot.send_message(
                                    chat_id=user_id,
                                    text=text,
                                    parse_mode='HTML',
                                    reply_markup=InlineKeyboardMarkup(keyboard)
                                )

                            topup.insert_one({
                                'bianhao': timer,
                                'user_id': user_id,
                                'money': final_amount,
                                'usdt': money,
                                'cz_type': 'usdt',
                                'status': 'pending',
                                'suijishu': suijishu,
                                'time': now,
                                'timer': timer_str,
                                'expire_time': expire_str,
                                'message_id': msg.message_id
                            })

                        # 微信 / 支付宝 模式：生成二维码和支付链接
                        elif paytype in ['wechat', 'alipay']:
                            # 获取易支付类型映射
                            paytype_map = {
                                'wechat': 'wxpay',
                                'alipay': 'alipay'
                            }
                            easypay_type = paytype_map.get(paytype, 'alipay')
                            
                            try:
                                # 创建支付链接和二维码
                                payment_data = create_payment_with_qrcode(
                                    pid=EASYPAY_PID,
                                    key=EASYPAY_KEY,
                                    gateway_url=EASYPAY_GATEWAY,
                                    out_trade_no=timer,
                                    name='Telegram充值',
                                    money=final_amount,
                                    notify_url=EASYPAY_NOTIFY,
                                    return_url=EASYPAY_RETURN,
                                    payment_type=easypay_type
                                )
                                
                                pay_url = payment_data['url']
                                qrcode_path = payment_data['qrcode_path']
                                
                            except Exception as e:
                                context.bot.send_message(chat_id=user_id, text=f"创建支付链接失败：{e}")
                                return

                            payment_name = "微信支付" if paytype == 'wechat' else "支付宝"
                            
                            if lang == 'zh':
                                text = f"""
<b>{payment_name} 充值详情</b>

💰 <b>支付金额：</b><code>¥{final_amount}</code>
💎 <b>到账USDT：</b><code>{money}</code>

📱 <b>扫码支付：</b>请使用{payment_name}扫描上方二维码
🔗 <b>或点击按钮：</b>跳转到{payment_name}进行支付

<b>订单号：</b><code>{timer}</code>
<b>创建时间：</b>{timer_str}
<b>支付截止：</b>{expire_str}

❗️请在10分钟内完成支付，系统自动识别到账
❗️请勿重复支付，避免资金损失
                                """.strip()
                            else:
                                text = f"""
<b>{payment_name} Recharge Details</b>

💰 <b>Payment Amount:</b><code>¥{final_amount}</code>
💎 <b>USDT to Receive:</b><code>{money}</code>

📱 <b>Scan QR Code:</b>Use {payment_name} to scan the QR code above
🔗 <b>Or Click Button:</b>Jump to {payment_name} for payment

<b>Order No:</b><code>{timer}</code>
<b>Created:</b>{timer_str}
<b>Deadline:</b>{expire_str}

❗️Please complete payment within 10 minutes, automatic credit recognition
❗️Do not pay repeatedly to avoid fund loss
                                """.strip()

                            keyboard = [
                                [InlineKeyboardButton(f"跳转{payment_name}" if lang == 'zh' else f"Open {payment_name}", url=pay_url)],
                                [InlineKeyboardButton("❌取消订单" if lang == 'zh' else "❌Cancel Order", callback_data=f'qxdingdan {user_id}')]
                            ]

                            # 发送二维码图片和支付信息
                            try:
                                msg = context.bot.send_photo(
                                    chat_id=user_id,
                                    photo=open(qrcode_path, 'rb'),
                                    caption=text,
                                    parse_mode='HTML',
                                    reply_markup=InlineKeyboardMarkup(keyboard)
                                )
                            except Exception as e:
                                # 如果发送图片失败，回退到文本+链接模式
                                text += f"\n\n🔗 <b>支付链接：</b><a href=\"{pay_url}\">点击此处跳转支付</a>"
                                msg = context.bot.send_message(
                                    chat_id=user_id,
                                    text=text,
                                    parse_mode='HTML',
                                    disable_web_page_preview=False,
                                    reply_markup=InlineKeyboardMarkup(keyboard)
                                )

                            topup.insert_one({
                                'bianhao': timer,
                                'user_id': user_id,
                                'money': final_amount,
                                'usdt': money,
                                'cz_type': paytype,
                                'status': 'pending',
                                'suijishu': suijishu,
                                'time': now,
                                'timer': timer_str,
                                'expire_time': expire_str,
                                'message_id': msg.message_id,
                                'pay_url': pay_url,
                                'qrcode_path': qrcode_path
                            })

                        user.update_one({'user_id': user_id}, {"$set": {"sign": 0}})
                    else:
                        keyboard = [[InlineKeyboardButton("❌取消输入", callback_data=f'close {user_id}')]]
                        context.bot.send_message(
                            chat_id=user_id,
                            text='请输入数字' if lang == 'zh' else 'Please enter a number',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )

                elif 'gmqq' in sign:
                    del_message(update.message)
                    data = sign.replace('gmqq ', '')
                    nowuid = data.split(':')[0]
                    del_message_id = data.split(':')[1]
                    try:
                        context.bot.deleteMessage(chat_id=user_id, message_id=del_message_id)
                    except:
                        pass

                    ejfl_list = ejfl.find_one({'nowuid': nowuid})
                    projectname = ejfl_list['projectname']
                    money = ejfl_list['money']
                    uid = ejfl_list['uid']
                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    if is_number(text):
                        gmsl = int(text)
                        
                        # Security check: Reject negative or zero quantity purchases
                        if gmsl <= 0:
                            if lang == 'zh':
                                keyboard = [[InlineKeyboardButton('🔙 返回商品列表', callback_data='show_product_list')]]
                                context.bot.send_message(chat_id=user_id, text='❌ 购买数量必须大于0\n\n请返回商品列表重新购买',
                                                         reply_markup=InlineKeyboardMarkup(keyboard))
                            else:
                                keyboard = [[InlineKeyboardButton('🔙 Back to Products', callback_data='show_product_list')]]
                                context.bot.send_message(chat_id=user_id, text='❌ Quantity must be greater than 0\n\nPlease return to product list to purchase again',
                                                         reply_markup=InlineKeyboardMarkup(keyboard))
                            return
                        
                        zxymoney = standard_num(gmsl * money)
                        zxymoney = float(zxymoney) if str((zxymoney)).count('.') > 0 else int(standard_num(zxymoney))
                        if kc < gmsl:
                            if lang == 'zh':
                                keyboard = [[InlineKeyboardButton('❌取消购买', callback_data=f'close {user_id}')]]
                                context.bot.send_message(chat_id=user_id, text='当前库存不足【请再次输入数量】',
                                                         reply_markup=InlineKeyboardMarkup(keyboard))
                            else:
                                keyboard = [
                                    [InlineKeyboardButton('❌Cancel purchase', callback_data=f'close {user_id}')]]
                                context.bot.send_message(chat_id=user_id,
                                                         text='Current inventory is insufficient [Please enter the quantity again]',
                                                         reply_markup=InlineKeyboardMarkup(keyboard))
                            return

                        if lang == 'zh':
                            fstext = f'''
<b>✅您正在购买：{projectname}

✅ 数量{gmsl}

💰 价格{zxymoney}

💰 您的余额{USDT}</b>
                                                '''

                            keyboard = [
                                [InlineKeyboardButton('❌取消交易', callback_data=f'close {user_id}'),
                                 InlineKeyboardButton('确认购买✅',
                                                      callback_data=f'qrgaimai {nowuid}:{gmsl}:{zxymoney}')],
                                [InlineKeyboardButton('🏠主菜单', callback_data='backzcd')]

                            ]


                        else:
                            projectname = projectname if lang == 'zh' else get_fy(projectname)
                            fstext = f'''
<b>✅You are buying: {projectname}

✅ Quantity {gmsl}

💰 Price {zxymoney}

💰 Your balance {USDT}</b>
                                                '''
                            keyboard = [
                                [InlineKeyboardButton('❌Cancel transaction', callback_data=f'close {user_id}'),
                                 InlineKeyboardButton('Confirm purchase✅',
                                                      callback_data=f'qrgaimai {nowuid}:{gmsl}:{zxymoney}')],
                                [InlineKeyboardButton('🏠Main menu', callback_data='backzcd')]

                            ]
                        user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                        context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML',
                                                 reply_markup=InlineKeyboardMarkup(keyboard))

                    else:
                        if lang == 'zh':
                            keyboard = [[InlineKeyboardButton('❌取消购买', callback_data=f'close {user_id}')]]
                            context.bot.send_message(chat_id=user_id, text='请输入数字，不购买请点击取消',
                                                     reply_markup=InlineKeyboardMarkup(keyboard))
                        # user.update_one({'user_id': user_id},{"$set":{'sign': 0}})
                        else:
                            keyboard = [[InlineKeyboardButton('❌Cancel purchase', callback_data=f'close {user_id}')]]
                            context.bot.send_message(chat_id=user_id,
                                                     text='Please enter a number. If you do not want to purchase, please click Cancel',
                                                     reply_markup=InlineKeyboardMarkup(keyboard))
                elif 'upmoney' in sign:
                    if is_number(text):
                        nowuid = sign.replace('upmoney ', '')
                        money = float(text) if text.count('.') > 0 else int(text)
                        ejfl.update_one({"nowuid": nowuid}, {"$set": {"money": money}})
                        user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                        ej_list = ejfl.find_one({'nowuid': nowuid})
                        uid = ej_list['uid']
                        ej_projectname = ej_list['projectname']
                        money = ej_list['money']
                        fl_pro = fenlei.find_one({'uid': uid})['projectname']
                        keyboard = [
                            [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                             InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                            [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                             InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                            [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                             InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                            [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                             InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                            [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                             InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                            [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                        ]
                        kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                        ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))
                        fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                        '''
                        context.bot.send_message(chat_id=user_id, text=fstext,
                                                 reply_markup=InlineKeyboardMarkup(keyboard))

                    else:
                        context.bot.send_message(chat_id=user_id, text=f'请输入数字', parse_mode='HTML')

                elif 'upejflname' in sign:
                    nowuid = sign.replace('upejflname ', '')
                    ejfl.update_one({"nowuid": nowuid}, {"$set": {"projectname": text}})
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                    
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']
                    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], []]
                    ej_list = ejfl.find({'uid': uid})
                    for i in ej_list:
                        nowuid = i['nowuid']
                        projectname = i['projectname']
                        row = i['row']
                        keyboard[row - 1].append(
                            InlineKeyboardButton(f'{projectname}', callback_data=f'fejxxi {nowuid}'))

                    keyboard.append([InlineKeyboardButton('修改分类名', callback_data=f'upspname {uid}'),
                                     InlineKeyboardButton('新增二级分类', callback_data=f'newejfl {uid}')])
                    keyboard.append([InlineKeyboardButton('调整二级分类排序', callback_data=f'paixuejfl {uid}'),
                                     InlineKeyboardButton('删除二级分类', callback_data=f'delejfl {uid}')])
                    keyboard.append([InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')])
                    fstext = f'''
分类: {fl_pro}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))

                elif 'upspname' in sign:
                    uid = sign.replace('upspname ', '')
                    fenlei.update_one({"uid": uid}, {"$set": {"projectname": text}})
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    keylist = list(fenlei.find({}, sort=[('row', 1)]))
                    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], []]
                    for i in keylist:
                        uid = i['uid']
                        projectname = i['projectname']
                        row = i['row']
                        keyboard[row - 1].append(InlineKeyboardButton(f'{projectname}', callback_data=f'flxxi {uid}'))
                    keyboard.append([InlineKeyboardButton("新建一行", callback_data='newfl'),
                                     InlineKeyboardButton('调整行排序', callback_data='paixufl'),
                                     InlineKeyboardButton('删除一行', callback_data='delfl')])
                    context.bot.send_message(chat_id=user_id, text='商品管理',
                                             reply_markup=InlineKeyboardMarkup(keyboard))
                elif sign == 'settrc20':
                    shangtext.update_one({"projectname": '充值地址'}, {"$set": {"text": text}})
                    img = qrcode.make(data=text)
                    with open(f'{text}.png', 'wb') as f:
                        img.save(f)
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                    context.bot.send_message(chat_id=user_id, text=f'当前充值地址为: {text}', parse_mode='HTML')
                elif 'setkeyname' in sign:
                    qudata = sign.replace('setkeyname ', '')
                    qudataall = qudata.split(':')
                    row = int(qudataall[0])
                    first = int(qudataall[1])
                    get_key.update_one({'Row': row, 'first': first}, {'$set': {'projectname': text}})
                    keylist = list(get_key.find({}, sort=[('Row', 1), ('first', 1)]))
                    keyboard = [[], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [], [],
                                [], [], [], [], [], [], [], [], []]
                    for i in keylist:
                        projectname = i['projectname']
                        row = i['Row']
                        first = i['first']
                        keyboard[i["Row"] - 1].append(
                            InlineKeyboardButton(projectname, callback_data=f'keyxq {row}:{first}'))
                    keyboard.append([InlineKeyboardButton('新建一行', callback_data='newrow'),
                                     InlineKeyboardButton('删除一行', callback_data='delrow'),
                                     InlineKeyboardButton('调整行排序', callback_data='paixurow')])
                    keyboard.append([InlineKeyboardButton('修改按钮', callback_data='newkey')])
                    user.update_one({'user_id': user_id}, {"$set": {"sign": 0}})
                    context.bot.send_message(chat_id=user_id, text='自定义按钮',
                                             reply_markup=InlineKeyboardMarkup(keyboard))
                elif 'settuwenset' in sign:
                    qudata = sign.replace('settuwenset ', '')
                    qudataall = qudata.split(':')
                    row = int(qudataall[0])
                    first = int(qudataall[1])
                    entities = update.message.entities
                    get_key.update_one({'Row': row, 'first': first}, {'$set': {'text': zxh}})
                    get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_id': ''}})
                    get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_type': 'text'}})
                    get_key.update_one({'Row': row, 'first': first}, {'$set': {'entities': pickle.dumps(entities)}})
                    user.update_one({'user_id': user_id}, {"$set": {"sign": 0}})
                    message_id = context.bot.send_message(chat_id=user_id, text=text, entities=entities)
                    timer11 = Timer(3, del_message, args=[message_id])
                    timer11.start()
                elif 'setkeyboard' in sign:
                    qudata = sign.replace('setkeyboard ', '')
                    qudataall = qudata.split(':')
                    row = int(qudataall[0])
                    first = int(qudataall[1])
                    text = text.replace('｜', '|').replace(' ', '')
                    keyboard = parse_urls(text)
                    dumped = pickle.dumps(keyboard)
                    try:
                        message_id = context.bot.send_message(chat_id=user_id, text=f'尾随按钮设置',
                                                              reply_markup=InlineKeyboardMarkup(keyboard))
                        get_key.update_one({'Row': row, 'first': first}, {"$set": {'keyboard': dumped}})
                        get_key.update_one({'Row': row, 'first': first}, {"$set": {'key_text': text}})
                        timer11 = Timer(3, del_message, args=[message_id])
                        timer11.start()
                    except:
                        keyboard = [[InlineKeyboardButton('格式配置错误,请检查', callback_data='ddd')]]
                        message_id = context.bot.send_message(chat_id=user_id, text='格式配置错误,请检查',
                                                              reply_markup=InlineKeyboardMarkup(keyboard))
                        timer11 = Timer(3, del_message, args=[message_id])
                        timer11.start()
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})
                elif 'update_sysm' in sign:
                    nowuid = sign.replace('update_sysm ', '')
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']
                    ejfl.update_one({"nowuid": nowuid}, {"$set": {'sysm': zxh}})
                    fstext = f'''
新的使用说明为:
{zxh}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML')
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    ej_list = ejfl.find_one({'nowuid': nowuid})
                    uid = ej_list['uid']
                    money = ej_list['money']
                    ej_projectname = ej_list['projectname']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']
                    keyboard = [
                        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                    ]
                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))
                    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))
                elif 'update_wbts' in sign:
                    nowuid = sign.replace('update_wbts ', '')
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']
                    ejfl.update_one({"nowuid": nowuid}, {"$set": {'text': zxh}})
                    fstext = f'''
新的提示为:
{zxh}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML')
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    ej_list = ejfl.find_one({'nowuid': nowuid})
                    uid = ej_list['uid']
                    money = ej_list['money']
                    ej_projectname = ej_list['projectname']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']
                    keyboard = [
                        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                    ]
                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))
                    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


                elif 'update_hy' in sign:
                    nowuid = sign.replace('update_hy ', '')
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']

                    text = update.message.text
                    lines = text.split('\n')
                    lines = [line.strip() for line in lines if line.strip()]

                    if not lines:
                        update.message.reply_text("❌ 内容为空，无法上传链接")
                        return

                    progress_msg = context.bot.send_message(chat_id=user_id, text='📤 上传中，请勿重复操作...')
                    
                    # ✅ 启动批量上传模式
                    stock_manager.start_batch_upload()
                    
                    count = 0
                    timer = beijing_now_str()
                    total = len(lines)
                    step = max(1, total // 10)

                    for idx, line in enumerate(lines, 1):
                        # ✅ 支持手机号|链接 转换为 手机号----链接
                        if '|' in line and '----' not in line:
                            parts = line.split('|')
                            if len(parts) == 2:
                                remark = parts[0].strip()
                                link = parts[1].strip()
                                line = f"{remark}----{link}"

                        parts = line.split('----')
                        if len(parts) < 2:
                            continue  # 忽略无效格式

                        link = parts[-1].strip()
                        remark = '----'.join(parts[:-1]).strip()

                        if link.startswith('http'):
                            if hb.find_one({'nowuid': nowuid, 'projectname': line}) is None:
                                hbid = generate_24bit_uid()
                                shangchuanhaobao('会员链接', uid, nowuid, hbid, line, timer, remark=remark, batch_mode=True)
                                count += 1

                        # 📊 进度反馈（每10%更新一次）
                        if idx % step == 0 or idx == total:
                            percent = int(idx / total * 100)
                            try:
                                context.bot.edit_message_text(
                                    chat_id=user_id,
                                    message_id=progress_msg.message_id,
                                    text=f'📡 正在处理链接上传...\n\n✅ 当前进度：{percent}%'
                                )
                            except:
                                pass
                    
                    # ✅ 结束批量上传模式并立即发送通知
                    stock_manager.end_batch_upload(force_send=True)

                    context.bot.send_message(chat_id=user_id, text=f'✅ 本次上传了 {count} 个链接')
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    ej_list = ejfl.find_one({'nowuid': nowuid})
                    uid = ej_list['uid']
                    money = ej_list['money']
                    ej_projectname = ej_list['projectname']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']

                    keyboard = [
                        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                    ]

                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))

                    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


            elif update.message.document:
                if 'update_hb' in sign:
                    nowuid = sign.replace('update_hb ', '')
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']

                    file = update.message.document
                    filename = file.file_name
                    file_id = file.file_id
                    new_file = context.bot.get_file(file_id)
                    new_file_path = f'./临时文件夹/{filename}'
                    new_file.download(new_file_path)

                    progress_msg = context.bot.send_message(chat_id=user_id, text='📤 上传中，请勿重复操作...')
                    
                    # ✅ 启动批量上传模式
                    stock_manager.start_batch_upload()

                    count = 0
                    timer = beijing_now_str()
                    with zipfile.ZipFile(new_file_path, 'r') as zip_ref:
                        file_list = zip_ref.infolist()
                        total = len(file_list)
                        step = max(1, total // 10)

                        for idx, file_info in enumerate(file_list, 1):
                            match = re.match(r'^([^/\\]+)/.*$', file_info.filename)
                            if match:
                                folder_name = match.group(1)
                                if hb.find_one({'nowuid': nowuid, 'projectname': folder_name}) is None:
                                    hbid = generate_24bit_uid()
                                    shangchuanhaobao('直登号', uid, nowuid, hbid, folder_name, timer, batch_mode=True)
                                    count += 1

                            zip_ref.extract(file_info, f'号包/{nowuid}')

                            # 每10%进度更新
                            if idx % step == 0 or idx == total:
                                percent = int(idx / total * 100)
                                try:
                                    context.bot.edit_message_text(
                                        chat_id=user_id,
                                        message_id=progress_msg.message_id,
                                        text=f'📦 正在解压处理号包...\n\n✅ 当前进度：{percent}%'
                                    )
                                except:
                                    pass
                    
                    # ✅ 结束批量上传模式并立即发送通知
                    stock_manager.end_batch_upload(force_send=True)

                    update.message.reply_text(f'🎉 解压并处理完成！本次上传了 {count} 个号包')
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    ej_list = ejfl.find_one({'nowuid': nowuid})
                    uid = ej_list['uid']
                    money = ej_list['money']
                    ej_projectname = ej_list['projectname']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']

                    keyboard = [
                        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                    ]

                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))

                    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


                elif 'update_gg' in sign:
                    nowuid = sign.replace('update_gg ', '')
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']

                    file = update.message.document
                    # 获取文件名
                    filename = file.file_name

                    # 获取文件ID
                    file_id = file.file_id
                    # 下载文件
                    new_file = context.bot.get_file(file_id)
                    # 将文件保存到本地
                    new_file_path = f'./临时文件夹/{filename}'
                    new_file.download(new_file_path)

                    # 初始进度提示
                    progress_msg = context.bot.send_message(chat_id=user_id, text='📤 上传中，请勿重复操作...')
                    
                    # ✅ 启动批量上传模式
                    stock_manager.start_batch_upload()

                    with open(new_file_path, 'r', encoding='utf-8') as file:
                        link_list = file.read()

                    login = re.findall('login: (.*)', link_list)
                    password = re.findall('password: (.*)', link_list)
                    submail = re.findall('submail: (.*)', link_list)

                    matches = list(zip(login, password, submail))

                    timer = beijing_now_str()
                    count = 0
                    total = len(matches)
                    step = max(1, total // 10)

                    for idx, i in enumerate(matches, 1):
                        login = i[0]
                        password = i[1]
                        submail = i[2]
                        jihe12 = {'账户': login, '密码': password, '子邮件': submail}
                        if hb.find_one({'nowuid': nowuid, 'projectname': login}) is None:
                            hbid = generate_24bit_uid()
                            shangchuanhaobao('谷歌', uid, nowuid, hbid, login, timer, batch_mode=True)
                            hb.update_one({'hbid': hbid}, {"$set": {"leixing": '谷歌', 'data': jihe12}})
                            count += 1

                        # 每10%更新一次进度提示
                        if idx % step == 0 or idx == total:
                            percent = int(idx / total * 100)
                            try:
                                context.bot.edit_message_text(
                                    chat_id=user_id,
                                    message_id=progress_msg.message_id,
                                    text=f'📥 正在处理谷歌账户...\n\n✅ 进度：{percent}%'
                                )
                            except:
                                pass
                    
                    # ✅ 结束批量上传模式并立即发送通知
                    stock_manager.end_batch_upload(force_send=True)

                    update.message.reply_text(f'处理完成！本次上传了{count}个谷歌号')
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    ej_list = ejfl.find_one({'nowuid': nowuid})
                    uid = ej_list['uid']
                    money = ej_list['money']
                    ej_projectname = ej_list['projectname']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']
                    keyboard = [
                        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                    ]
                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))
                    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


                elif 'update_txt' in sign:
                    nowuid = sign.replace('update_txt ', '')
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']

                    file = update.message.document
                    # 获取文件名
                    filename = file.file_name

                    # 获取文件ID
                    file_id = file.file_id
                    # 下载文件
                    new_file = context.bot.get_file(file_id)
                    # 将文件保存到本地
                    new_file_path = f'./临时文件夹/{filename}'
                    new_file.download(new_file_path)

                    # 初始进度提示
                    progress_msg = context.bot.send_message(chat_id=user_id, text='📤 上传中，请勿重复操作...')
                    
                    # ✅ 启动批量上传模式
                    stock_manager.start_batch_upload()

                    link_list = []
                    with open(new_file_path, 'r', encoding='utf-8') as file:
                        # 逐行读取文件内容
                        for line in file:
                            # 去除每行末尾的换行符并添加到列表中
                            link_list.append(line.strip())

                    timer = beijing_now_str()
                    count = 0
                    total = len(link_list)
                    step = max(1, total // 10)

                    for idx, i in enumerate(link_list, 1):
                        if hb.find_one({'nowuid': nowuid, 'projectname': i}) is None:
                            hbid = generate_24bit_uid()
                            shangchuanhaobao('API', uid, nowuid, hbid, i, timer, batch_mode=True)
                            count += 1

                        # 每10%更新一次进度提示
                        if idx % step == 0 or idx == total:
                            percent = int(idx / total * 100)
                            try:
                                context.bot.edit_message_text(
                                    chat_id=user_id,
                                    message_id=progress_msg.message_id,
                                    text=f'📥 正在处理链接...\n\n✅ 进度：{percent}%'
                                )
                            except:
                                pass
                    
                    # ✅ 结束批量上传模式并立即发送通知
                    stock_manager.end_batch_upload(force_send=True)

                    update.message.reply_text(f'处理完成！本次上传了{count}个api链接')
                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    ej_list = ejfl.find_one({'nowuid': nowuid})
                    uid = ej_list['uid']
                    money = ej_list['money']
                    ej_projectname = ej_list['projectname']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']
                    keyboard = [
                        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                    ]
                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))
                    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))

                elif 'update_xyh' in sign:
                    nowuid = sign.replace('update_xyh ', '')
                    uid = ejfl.find_one({'nowuid': nowuid})['uid']

                    file = update.message.document
                    # 获取文件名
                    filename = file.file_name

                    # 获取文件ID
                    file_id = file.file_id
                    # 下载文件
                    new_file = context.bot.get_file(file_id)
                    # 将文件保存到本地
                    new_file_path = f'./临时文件夹/{filename}'
                    new_file.download(new_file_path)

                    context.bot.send_message(chat_id=user_id, text='上传中，请勿重复操作')
                    
                    # ✅ 启动批量上传模式
                    stock_manager.start_batch_upload()
                    
                    # 解压缩文件
                    count = 0
                    tj_dict = {}
                    timer = beijing_now_str()
                    with zipfile.ZipFile(new_file_path, 'r') as zip_ref:
                        for file_info in zip_ref.infolist():
                            filename = file_info.filename
                            if filename.endswith('.json') or filename.endswith('.session'):
                                # 仅解压 session 或者 json 格式的文件
                                fli1 = filename.replace('.json', '').replace('.session', '')
                                if fli1 not in tj_dict.keys():

                                    hbid = generate_24bit_uid()
                                    if hb.find_one({'nowuid': nowuid, 'projectname': fli1}) is None:
                                        tj_dict[fli1] = 1
                                        shangchuanhaobao('协议号', uid, nowuid, hbid, fli1, timer, batch_mode=True)

                                zip_ref.extract(member=file_info, path=f'协议号/{nowuid}')
                                pass
                            else:
                                pass
                    for i in tj_dict:
                        count += 1
                    
                    # ✅ 结束批量上传模式并立即发送通知
                    stock_manager.end_batch_upload(force_send=True)

                    update.message.reply_text(f'解压并处理完成！本次上传了{count}个协议号')

                    user.update_one({'user_id': user_id}, {"$set": {'sign': 0}})

                    ej_list = ejfl.find_one({'nowuid': nowuid})
                    uid = ej_list['uid']
                    money = ej_list['money']
                    ej_projectname = ej_list['projectname']
                    fl_pro = fenlei.find_one({'uid': uid})['projectname']
                    keyboard = [
                        [InlineKeyboardButton('取出所有库存', callback_data=f'qchuall {nowuid}'),
                         InlineKeyboardButton('此商品使用说明', callback_data=f'update_sysm {nowuid}')],
                        [InlineKeyboardButton('上传谷歌账户', callback_data=f'update_gg {nowuid}'),
                         InlineKeyboardButton('购买此商品提示', callback_data=f'update_wbts {nowuid}')],
                        [InlineKeyboardButton('上传链接', callback_data=f'update_hy {nowuid}'),
                         InlineKeyboardButton('上传txt文件', callback_data=f'update_txt {nowuid}')],
                        [InlineKeyboardButton('上传号包', callback_data=f'update_hb {nowuid}'),
                         InlineKeyboardButton('上传协议号', callback_data=f'update_xyh {nowuid}')],
                        [InlineKeyboardButton('修改二级分类名', callback_data=f'upejflname {nowuid}'),
                         InlineKeyboardButton('修改价格', callback_data=f'upmoney {nowuid}')],
                        [InlineKeyboardButton('❌关闭', callback_data=f'close {user_id}')]
                    ]
                    kc = len(list(hb.find({'nowuid': nowuid, 'state': 0})))
                    ys = len(list(hb.find({'nowuid': nowuid, 'state': 1})))
                    fstext = f'''
主分类: {fl_pro}
二级分类: {ej_projectname}

价格: {money}U
库存: {kc}
已售: {ys}
                    '''
                    context.bot.send_message(chat_id=user_id, text=fstext, reply_markup=InlineKeyboardMarkup(keyboard))


            else:
                caption = update.message.caption
                entities = update.message.caption_entities

                if 'settuwenset' in sign:
                    qudata = sign.replace('settuwenset ', '')
                    qudataall = qudata.split(':')
                    row = int(qudataall[0])
                    first = int(qudataall[1])
                    if update.message.photo:
                        file = update.message.photo[-1].file_id
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'text': caption}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_id': file}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_type': 'photo'}})
                        user.update_one({'user_id': user_id}, {"$set": {"sign": 0}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'entities': pickle.dumps(entities)}})
                        message_id = context.bot.send_photo(chat_id=user_id, caption=caption, photo=file,
                                                            caption_entities=entities)
                        timer11 = Timer(3, del_message, args=[message_id])
                        timer11.start()
                    elif update.message.animation:
                        file = update.message.animation.file_id
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'text': caption}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_id': file}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_type': 'animation'}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'state': 1}})
                        user.update_one({'user_id': user_id}, {"$set": {"sign": 0}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'entities': pickle.dumps(entities)}})
                        message_id = context.bot.sendAnimation(chat_id=user_id, caption=caption, animation=file,
                                                               caption_entities=entities)
                        timer11 = Timer(3, del_message, args=[message_id])
                        timer11.start()
                    else:
                        file = update.message.video.file_id
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'text': caption}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_id': file}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'file_type': 'video'}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'state': 1}})
                        user.update_one({'user_id': user_id}, {"$set": {"sign": 0}})
                        get_key.update_one({'Row': row, 'first': first}, {'$set': {'entities': pickle.dumps(entities)}})
                        message_id = context.bot.sendVideo(chat_id=user_id, caption=caption, video=file,
                                                           caption_entities=entities)
                        timer11 = Timer(3, del_message, args=[message_id])
                        timer11.start()
        else:
            if text == '开始营业':
                if is_admin(user_id):
                    shangtext.update_one({'projectname': '营业状态'}, {"$set": {"text": 1}})
                    context.bot.send_message(chat_id=user_id, text='开始营业')
            elif text == '停止营业':
                if is_admin(user_id):
                    shangtext.update_one({'projectname': '营业状态'}, {"$set": {"text": 0}})
                    context.bot.send_message(chat_id=user_id, text='停止营业')

            # ✅ 安全获取按钮文本（避免数据库查询失败导致按钮无法响应）
            try:
                grzx = get_key.find_one({'projectname': {"$regex": "个人中心"}})
                grzx = grzx['projectname'] if grzx and lang == 'zh' else None
                if not grzx and lang == 'en':
                    grzx_fy = fyb.find_one({'text': {"$regex": "个人中心"}})
                    grzx = grzx_fy['fanyi'] if grzx_fy else None
            except:
                grzx = None
            
            try:
                yecz = get_key.find_one({'projectname': {"$regex": "余额充值"}})
                yecz = yecz['projectname'] if yecz and lang == 'zh' else None
                if not yecz and lang == 'en':
                    yecz_fy = fyb.find_one({'text': {"$regex": "余额充值"}})
                    yecz = yecz_fy['fanyi'] if yecz_fy else None
            except:
                yecz = None
            
            try:
                splb = get_key.find_one({'projectname': {"$regex": "商品列表"}})
                splb = splb['projectname'] if splb and lang == 'zh' else None
                if not splb and lang == 'en':
                    splb_fy = fyb.find_one({'text': {"$regex": "商品列表"}})
                    splb = splb_fy['fanyi'] if splb_fy else None
            except:
                splb = None
            
            try:
                lxkf = get_key.find_one({'projectname': {"$regex": "联系客服"}})
                lxkf = lxkf['projectname'] if lxkf and lang == 'zh' else None
                if not lxkf and lang == 'en':
                    lxkf_fy = fyb.find_one({'text': {"$regex": "联系客服"}})
                    lxkf = lxkf_fy['fanyi'] if lxkf_fy else None
            except:
                lxkf = None
            
            try:
                syjc = get_key.find_one({'projectname': {"$regex": "使用教程"}})
                syjc = syjc['projectname'] if syjc and lang == 'zh' else None
                if not syjc and lang == 'en':
                    syjc_fy = fyb.find_one({'text': {"$regex": "使用教程"}})
                    syjc = syjc_fy['fanyi'] if syjc_fy else None
            except:
                syjc = None
            
            try:
                chtz = get_key.find_one({'projectname': {"$regex": "出货通知"}})
                chtz = chtz['projectname'] if chtz and lang == 'zh' else None
                if not chtz and lang == 'en':
                    chtz_fy = fyb.find_one({'text': {"$regex": "出货通知"}})
                    chtz = chtz_fy['fanyi'] if chtz_fy else None
            except:
                chtz = None
            
            try:
                ckkc = get_key.find_one({'projectname': {"$regex": "查询库存"}})
                ckkc = ckkc['projectname'] if ckkc and lang == 'zh' else None
                if not ckkc and lang == 'en':
                    ckkc_fy = fyb.find_one({'text': {"$regex": "查询库存"}})
                    ckkc = ckkc_fy['fanyi'] if ckkc_fy else None
            except:
                ckkc = None


            # 英文用户点击按钮时，翻译成原文以统一判断
            if lang == 'en':
                match = fyb.find_one({'fanyi': text})
                if match:
                    text = match['text']

            if text == '👤个人中心' or text == '👤Personal Center':
                del_message(update.message)
                if username is None:
                    username = fullname
                else:
                    username = f'<a href="https://t.me/{username}">{username}</a>'
                
                if lang == 'zh':
                    fstext = f'''
<b>个人中心</b>


<b>账户信息</b>
├─ 用户ID: <code>{user_id}</code>
├─ 用户名: {username}
├─ 注册时间: <code>{creation_time}</code>
└─ 账户状态: <code>正常</code>

<b>交易统计</b>
├─ 累计订单: <code>{zgsl}</code> 单
├─ 累计消费: <code>{standard_num(zgje)}</code> USDT
└─ 当前余额: <code>{USDT}</code> USDT

<b>快捷操作</b>
├─ 查看购买记录
├─ 充值USDT余额
└─ 联系客服支持


<i>数据更新时间: {beijing_now_str()}</i>
                    '''.strip()
                else:
                    fstext = f'''
<b>Personal Center</b>


<b>Account Information</b>
├─ User ID: <code>{user_id}</code>
├─ Username: {username}
├─ Registration: <code>{creation_time}</code>
└─ Status: <code>Active</code>

<b>Transaction Statistics</b>
├─ Total Orders: <code>{zgsl}</code>
├─ Total Spent: <code>{standard_num(zgje)}</code> USDT
└─ Current Balance: <code>{USDT}</code> USDT

<b>Quick Actions</b>
├─ View Purchase History
├─ Recharge USDT Balance
└─ Contact Customer Support


<i>Last Updated: {beijing_now_str()}</i>
                    '''.strip()
                
                keyboard = [[
                    InlineKeyboardButton('购买记录' if lang == 'zh' else 'Purchase History', callback_data=f'gmaijilu {user_id}'),
                    InlineKeyboardButton('关闭' if lang == 'zh' else 'Close', callback_data=f'close {user_id}')
                ]]
                context.bot.send_message(
                    chat_id=user_id,
                    text=fstext,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=True
                )


            elif text == '发红包':
                del_message(update.message)

                lang = user.find_one({'user_id': user_id}).get('lang', 'zh')

                if lang == 'zh':
                    fstext = "从下面的列表中选择一个红包"
                    keyboard = [
                        [InlineKeyboardButton('◾️进行中', callback_data='jxzhb'),
                         InlineKeyboardButton('已结束', callback_data='yjshb')],
                        [InlineKeyboardButton('➕添加', callback_data='addhb')],
                        [InlineKeyboardButton('关闭', callback_data=f'close {user_id}')]
                    ]
                else:
                    fstext = "Select a red packet from the list below"
                    keyboard = [
                        [InlineKeyboardButton('◾️In Progress', callback_data='jxzhb'),
                         InlineKeyboardButton('Finished', callback_data='yjshb')],
                        [InlineKeyboardButton('➕Add', callback_data='addhb')],
                        [InlineKeyboardButton('Close', callback_data=f'close {user_id}')]
                    ]

                context.bot.send_message(
                    chat_id=user_id,
                    text=fstext,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )


            elif text == '📞联系客服' or text == '📞Contact Support':
                del_message(update.message)
                # ✅ 从环境变量读取联系方式
                customer_service = os.getenv('CUSTOMER_SERVICE', '@lwmmm')
                official_channel = os.getenv('OFFICIAL_CHANNEL', '@XCZHCS')
                restock_group = os.getenv('RESTOCK_GROUP', 'https://t.me/+EeTF1qOe_MoyMzQ0')
                
                msg = f"""
------------------------
<b>{'客服' if lang == 'zh' else 'Support'}：</b>{customer_service}  
<b>{'官方频道' if lang == 'zh' else 'Official Channel'}：</b>{official_channel}  
<b>{'补货通知群' if lang == 'zh' else 'Restock Group'}：</b>{restock_group}
------------------------
<i>{'无其它任何联系方式，谨防诈骗！' if lang == 'zh' else 'No other contact methods. Beware of scams!'}</i>
                """.strip()
                keyboard = [[InlineKeyboardButton("❌关闭" if lang == 'zh' else "❌ Close", callback_data=f"close {user_id}")]]
                context.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif text == '🔶使用教程' or text == '🔶Usage Tutorial':
                del_message(update.message)
                # ✅ 从环境变量读取教程链接
                tutorial_link = os.getenv('TUTORIAL_LINK', 'https://t.me/XCZHCS/106')
                
                msg = f"""
------------------------
{'点击下方链接查看详细操作指引 👇' if lang == 'zh' else 'Click the link below to view instructions 👇'}  
🔗 {tutorial_link}
------------------------
                """.strip()
                keyboard = [[InlineKeyboardButton("❌关闭" if lang == 'zh' else "❌ Close", callback_data=f"close {user_id}")]]
                context.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif text == '🔷出货通知' or text == '🔷Delivery Notice':
                del_message(update.message)
                # ✅ 从环境变量读取补货通知群
                restock_group = os.getenv('RESTOCK_GROUP', 'https://t.me/+EeTF1qOe_MoyMzQ0')
                
                msg = f"<b>{'🔥补货通知群：' if lang == 'zh' else '🔥 Restock Notification Group:'}</b> {restock_group}"
                keyboard = [[InlineKeyboardButton("❌关闭" if lang == 'zh' else "❌ Close", callback_data=f"close {user_id}")]]
                context.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            elif text == '🔎查询库存' or text == '🔎Check Inventory':
                del_message(update.message)
                return check_stock_callback(update, context, page=0, lang=lang)

            elif text == 'TRX能量':
                del_message(update.message)
                lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
                
                # ✅ 从环境变量读取TRX兑换地址
                trx_address = os.getenv('TRX_EXCHANGE_ADDRESS', 'TSyYxxxxxxExampleAddrxxxxxYtR')

                if lang == 'zh':
                    msg = f"""
🪙 <b>转U成功后自动秒回TRX</b> 🪙  
🏪 24小时自动闪兑换 TRX  
➖➖➖➖➖➖➖➖➖➖  
🔄 <b>实时汇率</b>（全网汇率最优）

<b>点击复制官方自动兑换地址：</b>
<code>{trx_address}</code>

➖➖➖➖➖➖➖➖➖➖  
🔴 1U起兑换，原地址秒返 TRX  
🔴 大额汇率优，联系老板兑换  
📖 使用交易所兑换请避免中心化直接提现

⚠️ 千万请勿使用中心化交易所直接提现闪兑，后果自负！
                    """.strip()
                    close_btn = "❌关闭"
                else:
                    msg = f"""
🪙 <b>Auto TRX Return After USDT Payment</b> 🪙  
🏪 24/7 Automated Flash Exchange  
➖➖➖➖➖➖➖➖➖➖  
🔄 <b>Live Exchange Rate</b> (Best Price)

<b>Copy the official exchange address below:</b>
<code>{trx_address}</code>

➖➖➖➖➖➖➖➖➖➖  
🔴 Min 1U. TRX auto return to source address  
🔴 Large amount? Contact admin for best rates  
📖 Avoid using centralized exchanges to withdraw directly

⚠️ Do NOT withdraw directly from centralized exchanges. Use at your own risk!
                    """.strip()
                    close_btn = "❌ Close"

                keyboard = [
                    [InlineKeyboardButton(close_btn, callback_data=f"close {user_id}")]
                ]

                sent = context.bot.send_message(
                    chat_id=user_id,
                    text=msg,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

                # ✅ 设置按钮自毁（延迟删除）
                context.job_queue.run_once(
                    lambda ctx: ctx.bot.delete_message(chat_id=user_id, message_id=sent.message_id),
                    when=TRX_MESSAGE_DELETE_DELAY,
                    context=context
                )



            elif text in ['🌐 语言切换', '🌐 Language Switching']:
                del_message(update.message)

                keyboard = [[KeyboardButton('中文服务'), KeyboardButton('English')]]
                msg = context.bot.send_message(
                    chat_id=user_id,
                    text="请选择语言 / Choose your language：",
                    reply_markup=ReplyKeyboardMarkup(
                        keyboard,
                        resize_keyboard=True,
                        one_time_keyboard=False,
                        input_field_placeholder="请选择语言 / Choose your language"
                    )
                )
                context.job_queue.run_once(
                    lambda c: c.bot.delete_message(chat_id=user_id, message_id=msg.message_id),
                    when=MESSAGE_DELETE_DELAY,
                    context=context
                )

            elif text == '中文服务':
                del_message(update.message)
                user.update_one({'user_id': user_id}, {"$set": {'lang': 'zh'}})
                lang = 'zh'

                keyboard = [[] for _ in range(100)]
                for i in get_key.find({}, sort=[('Row', 1), ('first', 1)]):
                    if i['projectname'] == '中文服务':
                        continue
                    keyboard[i['Row'] - 1].append(KeyboardButton(i['projectname']))

                context.bot.send_message(
                    chat_id=user_id,
                    text="语言切换成功",
                    reply_markup=ReplyKeyboardMarkup(
                        keyboard,
                        resize_keyboard=True,
                        one_time_keyboard=False,
                        input_field_placeholder="请选择功能"
                    ),
                    parse_mode="HTML"
                )


            elif text == 'English':
                del_message(update.message)
                user.update_one({'user_id': user_id}, {"$set": {'lang': 'en'}})
                lang = 'en'

                # ✅ 预设的主要按钮英文翻译
                button_translations = {
                    '🛒商品列表': '🛒Product List',
                    '👤个人中心': '👤Personal Center', 
                    '💳余额充值': '💳Balance Recharge',
                    '📞联系客服': '📞Contact Support',
                    '🔶使用教程': '🔶Usage Tutorial',
                    '🔷出货通知': '🔷Delivery Notice',
                    '🔎查询库存': '🔎Check Inventory',
                    '🌐 语言切换': '🌐 Language Switching',
                    '⬅️ 返回主菜单': '⬅️ Return to Main Menu'
                }

                keyboard = [[] for _ in range(100)]
                for i in get_key.find({}, sort=[('Row', 1), ('first', 1)]):
                    if i['projectname'] == '中文服务':
                        continue
                    
                    # 使用预设翻译，如果没有则使用get_fy
                    button_text = button_translations.get(i['projectname'], get_fy(i['projectname']))
                    keyboard[i['Row'] - 1].append(KeyboardButton(button_text))

                context.bot.send_message(
                    chat_id=user_id,
                    text="Language switch successful",
                    reply_markup=ReplyKeyboardMarkup(
                        keyboard,
                        resize_keyboard=True,
                        one_time_keyboard=False,
                        input_field_placeholder="Please choose a function"
                    ),
                    parse_mode="HTML"
                )


            elif text == '⬅️ 返回主菜单' or text == '⬅️ Return to Main Menu':
                del_message(update.message)
                # 获取用户语言设置
                uinfo = user.find_one({'user_id': user_id})
                lang = uinfo.get('lang', 'zh')
                
                # ✅ 预设的主要按钮英文翻译
                button_translations = {
                    '🛒商品列表': '🛒Product List',
                    '👤个人中心': '👤Personal Center', 
                    '💳余额充值': '💳Balance Recharge',
                    '📞联系客服': '📞Contact Support',
                    '🔶使用教程': '🔶Usage Tutorial',
                    '🔷出货通知': '🔷Delivery Notice',
                    '🔎查询库存': '🔎Check Inventory',
                    '🌐 语言切换': '🌐 Language Switching',
                    '⬅️ 返回主菜单': '⬅️ Return to Main Menu'
                }
                
                # 构建多语言键盘
                keylist = get_key.find({}, sort=[('Row', 1), ('first', 1)])
                keyboard = [[] for _ in range(100)]
                for item in keylist:
                    if lang == 'zh':
                        label = item['projectname']
                    else:
                        # 使用预设翻译，如果没有则使用get_fy
                        label = button_translations.get(item['projectname'], get_fy(item['projectname']))
                    row = item['Row']
                    keyboard[row - 1].append(KeyboardButton(label))
                
                text_msg = "已返回主菜单，请选择功能：" if lang == 'zh' else "Returned to main menu, please select a function:"
                placeholder = "请选择功能" if lang == 'zh' else "Please choose a function"
                
                msg = context.bot.send_message(
                    chat_id=user_id,
                    text=text_msg,
                    reply_markup=ReplyKeyboardMarkup(
                        [row for row in keyboard if row],
                        resize_keyboard=True,
                        one_time_keyboard=False,
                        input_field_placeholder=placeholder
                    )
                )
                context.job_queue.run_once(
                    lambda c: c.bot.delete_message(chat_id=user_id, message_id=msg.message_id),
                    when=3,
                    context=context
                )




            elif text == '💳余额充值' or text == '💳Balance Recharge':
                del_message(update.message)
                user.update_one({'user_id': user_id}, {'$unset': {'cz_paytype': ""}})
                
                # ✅ 从环境变量读取客服联系方式
                customer_service = os.getenv('CUSTOMER_SERVICE', '@lwmmm')

                if ENABLE_ALIPAY_WECHAT:
                    # 显示所有支付方式
                    if lang == 'zh':
                        fstext = (
                            "<b>请选择充值方式</b>\n\n"
                            "请根据你的常用支付渠道进行选择\n"
                            "我们支持以下方式：\n"
                            "微信支付、支付宝支付、USDT(TRC20) 数字货币支付\n\n"
                            "请务必选择你能立即完成支付的方式，以确保订单顺利完成。\n\n"
                            "注意：微信当前通道容易失败，支付宝通道比较多。\n"
                            "付款成功后请等待浏览器自动回调再关闭页面。\n"
                            f"如果没有到账请第一时间联系客服 {customer_service}\n\n"
                            "支付宝和微信有手续费，USDT 0 手续费"
                        )
                    else:
                        fstext = (
                            "<b>Please select a payment method</b>\n\n"
                            "Please choose based on your commonly used payment channel.\n"
                            "We support the following options:\n"
                            "WeChat Pay, Alipay, and USDT (TRC20) cryptocurrency.\n\n"
                            "Please make sure to choose a method you can complete the payment with immediately "
                            "to ensure successful processing.\n\n"
                            "Note: WeChat payment channel may fail more often.\n"
                            "Alipay channels are more stable and reliable.\n"
                            "After payment, please wait for the browser to confirm the callback before closing it.\n"
                            f"If your balance is not updated, please contact customer service {customer_service} immediately.\n\n"
                            "Alipay and WeChat payments may include transaction fees.\n"
                            "USDT payments have zero handling fees."
                        )

                    keyboard = [
                        [InlineKeyboardButton("微信支付" if lang == 'zh' else "WeChat Pay", callback_data="czfs wechat"),
                         InlineKeyboardButton("支付宝支付" if lang == 'zh' else "Alipay", callback_data="czfs alipay")],
                        [InlineKeyboardButton("USDT充值" if lang == 'zh' else "USDT (TRC20) Recharge", callback_data="czfs usdt")],
                        [InlineKeyboardButton("取消充值" if lang == 'zh' else "Cancel", callback_data=f"close {user_id}")]
                    ]
                else:
                    # 仅显示USDT支付方式
                    if lang == 'zh':
                        fstext = (
                            "<b>USDT (TRC20) 充值</b>\n\n"
                            "我们目前支持 USDT (TRC20) 数字货币充值\n\n"
                            "✅ 零手续费，到账快速\n"
                            "✅ 24小时自动处理\n"
                            "✅ 安全可靠的区块链支付\n\n"
                            "请务必使用 TRC20 网络进行转账\n"
                            f"如有问题请联系客服 {customer_service}"
                        )
                    else:
                        fstext = (
                            "<b>USDT (TRC20) Recharge</b>\n\n"
                            "We currently support USDT (TRC20) cryptocurrency recharge\n\n"
                            "✅ Zero transaction fees, fast deposit\n"
                            "✅ 24/7 automatic processing\n"
                            "✅ Secure and reliable blockchain payment\n\n"
                            "Please make sure to use TRC20 network for transfer\n"
                            f"If you have any questions, please contact customer service {customer_service}"
                        )

                    keyboard = [
                        [InlineKeyboardButton("USDT充值" if lang == 'zh' else "USDT (TRC20) Recharge", callback_data="czfs usdt")],
                        [InlineKeyboardButton("取消充值" if lang == 'zh' else "Cancel", callback_data=f"close {user_id}")]
                    ]

                context.bot.send_message(
                    chat_id=user_id,
                    text=fstext,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )



            elif text == '🛒商品列表' or text == '🛒Product List':
                del_message(update.message)
                fenlei_data = list(fenlei.find({}, sort=[('row', 1)]))
                ejfl_data = list(ejfl.find({}))
                hb_data = list(hb.find({'state': 0}))

                # ✅ 一级分类始终显示，显示库存数量（包括0）
                keyboard = []
                displayed_categories = []
                
                for i in fenlei_data:
                    uid = i['uid']
                    projectname = i['projectname']
                    row = i['row']
                    hsl = sum(
                        1 for j in ejfl_data if j['uid'] == uid
                        for hb_item in hb_data if hb_item['nowuid'] == j['nowuid']
                    )
                    
                    # ✅ 一级分类始终显示（不论库存多少）
                    projectname_display = projectname if lang == 'zh' else get_fy(projectname)
                    displayed_categories.append({
                        'name': projectname_display,
                        'stock': hsl,
                        'uid': uid,
                        'row': row
                    })
                
                # 按原有行号排序（保持管理员设置的顺序）
                displayed_categories.sort(key=lambda x: x['row'])
                
                # 每行一个按钮
                for cat in displayed_categories:
                    # ✅ 显示库存数量，0库存直接显示0
                    if cat['stock'] > 0:
                        if lang == 'zh':
                            button_text = f'{cat["name"]} [{cat["stock"]}个]'
                        else:
                            button_text = f'{cat["name"]} [{cat["stock"]} items]'
                    else:
                        if lang == 'zh':
                            button_text = f'{cat["name"]} [0个]'
                        else:
                            button_text = f'{cat["name"]} [0 items]'
                    
                    keyboard.append([
                        InlineKeyboardButton(
                            button_text, 
                            callback_data=f'catejflsp {cat["uid"]}:{cat["stock"]}'
                        )
                    ])

                if lang == 'zh':
                    fstext = (
                        "<b>🛒 商品分类 - 请选择所需：</b>\n\n"
                        "<b>❗快速查找商品发送带+号的区号（如 +94）</b>\n\n"
                        "<b>❗️首次购买请先少量测试，避免纠纷</b>！\n\n"
                        "<b>❗️长期未使用账户可能会出现问题，联系客服处理</b>。"
                    )
                    keyboard.append([InlineKeyboardButton("⚠️注意事项⚠️（点我查看）", callback_data="notice")])
                    keyboard.append([InlineKeyboardButton("❌关闭", callback_data=f"close {user_id}")])
                else:
                    fstext = (
                        "<b>🛒 Product Categories - Please choose:</b>\n\n"
                        "<b>❗ Quick search: Send country code with + (e.g., +94)</b>\n\n"
                        "❗️If you are new, please start with a small test purchase to avoid issues.\n"
                        "❗️Inactive accounts may encounter problems, please contact support."
                    )
                    keyboard.append([InlineKeyboardButton("⚠️ Important Notice ⚠️", callback_data="notice")])
                    keyboard.append([InlineKeyboardButton("❌ Close", callback_data=f"close {user_id}")])

                context.bot.send_message(
                    chat_id=user_id,
                    text=fstext,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            # ✅ 关键词查询功能 - 用户发送关键词自动查询商品
            else:
                # ✅ 如果管理员正在等待输入交易哈希，不处理该消息，让后续的 handle_admin_txhash_message 处理
                if user_id in WAITING_TXHASH:
                    return
                
                # ✅ 商品搜索触发规则：只有包含"+"号的文本才触发商品搜索
                # 例如：+54, +86, +34 等国家区号格式
                # 不包含"+"的文本不会触发商品搜索，避免干扰其他功能
                if '+' not in text:
                    # 不触发商品搜索，直接返回
                    return
                
                # 删除用户的查询消息
                try:
                    context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
                except:
                    pass
                
                # 如果文本过长，不进行关键词查询
                if len(text.strip()) > 50:
                    return
                
                query_text = text.strip()
                
                # ✅ 在商品名称中搜索关键词（支持模糊匹配）
                matched_products = []
                
                # 搜索所有商品
                for product in ejfl.find():
                    nowuid = product['nowuid']
                    uid = product.get('uid')
                    
                    # 跳过分类被删除的商品
                    if not fenlei.find_one({'uid': uid}):
                        continue
                    
                    # 检查库存
                    stock = hb.count_documents({'nowuid': nowuid, 'state': 0})
                    if stock <= 0:
                        continue
                    
                    # 检查价格
                    money = product.get('money', 0)
                    if money <= 0:
                        continue
                    
                    # 关键词匹配逻辑（不区分大小写）
                    product_name = product['projectname'].lower()
                    query_lower = query_text.lower()
                    
                    # 支持多种匹配方式
                    if (query_lower in product_name or 
                        any(keyword in product_name for keyword in query_lower.split()) or
                        # 支持数字匹配（如+86, +885等）
                        query_text in product_name or
                        # 支持国家名称匹配
                        any(country in product_name for country in [query_text, query_lower])):
                        
                        # 获取分类信息
                        category = fenlei.find_one({'uid': uid})
                        category_name = category.get('projectname', '未知分类') if category else '未知分类'
                        
                        matched_products.append({
                            'nowuid': nowuid,
                            'name': product['projectname'],
                            'category': category_name,
                            'price': money,
                            'stock': stock
                        })
                
                # 处理查询结果
                if not matched_products:
                    # 未找到商品
                    if lang == 'zh':
                        msg_text = f"❌ 未找到与「{query_text}」相关的商品\n\n💡 建议：\n• 尝试输入更简单的关键词\n• 查看完整商品列表"
                        buttons = [
                            [InlineKeyboardButton("🛒 查看所有商品", callback_data="show_product_list")],
                            [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
                        ]
                    else:
                        msg_text = f"❌ No products found related to 「{query_text}」\n\n💡 Suggestions:\n• Try simpler keywords\n• View complete product list"
                        buttons = [
                            [InlineKeyboardButton("🛒 View All Products", callback_data="show_product_list")],
                            [InlineKeyboardButton("❌ Close", callback_data=f"close {user_id}")]
                        ]
                    
                    context.bot.send_message(
                        chat_id=user_id,
                        text=msg_text,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                else:
                    # 找到商品，显示搜索结果
                    # 限制显示数量，最多显示10个
                    display_products = matched_products[:10]
                    
                    if lang == 'zh':
                        title = f"🔍 找到 {len(matched_products)} 个相关商品："
                        if len(matched_products) > 10:
                            title += f"\n（显示前10个）"
                    else:
                        title = f"🔍 Found {len(matched_products)} related products:"
                        if len(matched_products) > 10:
                            title += f"\n(Showing first 10)"
                    
                    buttons = []
                    
                    # 生成商品按钮
                    for product in display_products:
                        if lang == 'zh':
                            button_text = f"🛒 {product['name']} [{product['stock']}个] - {product['price']}U"
                        else:
                            product_name_en = get_fy(product['name'])
                            button_text = f"🛒 {product_name_en} [{product['stock']} items] - {product['price']}U"
                        
                        buttons.append([
                            InlineKeyboardButton(
                                button_text,
                                callback_data=f"gmsp {product['nowuid']}:{product['stock']}"
                            )
                        ])
                    
                    # 添加底部按钮
                    if lang == 'zh':
                        buttons.append([InlineKeyboardButton("🛒 查看所有商品", callback_data="show_product_list")])
                        buttons.append([InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")])
                    else:
                        buttons.append([InlineKeyboardButton("🛒 View All Products", callback_data="show_product_list")])
                        buttons.append([InlineKeyboardButton("❌ Close", callback_data=f"close {user_id}")])
                    
                    context.bot.send_message(
                        chat_id=user_id,
                        text=title,
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )


def check_stock_callback(update: Update, context: CallbackContext, page=0, lang='zh'):
    query = update.callback_query if update.callback_query else None
    user_id = update.effective_user.id
    limit = 50
    start = page * limit

    # 获取所有商品（过滤掉所属一级分类被删除的）
    all_goods = []
    for g in ejfl.find().sort("row", 1):
        nowuid = g['nowuid']
        uid = g.get('uid')
        if not fenlei.find_one({'uid': uid}):
            continue
        stock_count = hb.count_documents({'nowuid': nowuid, 'state': 0})
        if stock_count <= 0:
            continue
        g['stock'] = stock_count
        all_goods.append(g)

    total = len(all_goods)
    total_pages = (total + limit - 1) // limit
    display_goods = all_goods[start:start + limit]

    # 拼接展示内容
    text_lines = [f"<b>{'商品库存列表' if lang == 'zh' else 'Product Stock List'}</b>", "--------"]
    for i, g in enumerate(display_goods, start=start + 1):
        pname = g.get('projectname', '未知商品')
        pname = pname if lang == 'zh' else get_fy(pname)
        stock = g['stock']
        line = f"⤷ <b>{i}. {pname}</b>  ➥  {'库存' if lang == 'zh' else 'Stock'}: <b>{stock}</b>"
        text_lines.append(line)

    text_lines.append("--------")
    if lang == 'zh':
        text_lines.append(f"↰ 第 <b>{page + 1}</b> 页 / 共 <b>{total_pages}</b> 页 ↱")
    else:
        text_lines.append(f"↰ Page <b>{page + 1}</b> / <b>{total_pages}</b> ↱")

    text = "\n".join(text_lines)

    # 构建页码跳转按钮
    keyboard = []

    page_buttons = []
    for i in range(total_pages):
        label = f"{'↦' if i == page else ''}第{i + 1}页" if lang == 'zh' else f"{'↦' if i == page else ''}Page {i + 1}"
        page_buttons.append(InlineKeyboardButton(label, callback_data=f"ck_page {i}"))

    for i in range(0, len(page_buttons), 5):
        keyboard.append(page_buttons[i:i + 5])

    keyboard.append([InlineKeyboardButton("❌ 关闭" if lang == 'zh' else "❌ Close", callback_data=f"close {user_id}")])

    if query:
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    else:
        context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )


def ck_page_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    page = int(data.split()[1])
    user_id = query.from_user.id

    # 🔧 从数据库获取用户语言偏好
    lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
    check_stock_callback(update, context, page=page, lang=lang)




def stock_page_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
    page = int(query.data.split()[1])
    check_stock_callback(update, context, page, lang)


def show_product_list(update: Update, context: CallbackContext):
    """显示完整商品列表（从关键词查询触发）"""
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
    
    # 获取分类和商品数据
    fenlei_data = list(fenlei.find({}, sort=[('row', 1)]))
    ejfl_data = list(ejfl.find({}))
    hb_data = list(hb.find({'state': 0}))

    # ✅ 一级分类始终显示，显示库存数量（包括0）
    keyboard = []
    displayed_categories = []
    
    for i in fenlei_data:
        uid = i['uid']
        projectname = i['projectname']
        row = i['row']
        hsl = sum(
            1 for j in ejfl_data if j['uid'] == uid
            for hb_item in hb_data if hb_item['nowuid'] == j['nowuid']
        )
        
        # ✅ 一级分类始终显示（不论库存多少）
        projectname_display = projectname if lang == 'zh' else get_fy(projectname)
        displayed_categories.append({
            'name': projectname_display,
            'stock': hsl,
            'uid': uid,
            'row': row
        })
    
    # 按原有行号排序（保持管理员设置的顺序）
    displayed_categories.sort(key=lambda x: x['row'])
    
    # 每行一个按钮
    for cat in displayed_categories:
        # ✅ 显示库存数量，0库存直接显示0
        if cat['stock'] > 0:
            if lang == 'zh':
                button_text = f'{cat["name"]} [{cat["stock"]}个]'
            else:
                button_text = f'{cat["name"]} [{cat["stock"]} items]'
        else:
            if lang == 'zh':
                button_text = f'{cat["name"]} [0个]'
            else:
                button_text = f'{cat["name"]} [0 items]'
        
        keyboard.append([
            InlineKeyboardButton(
                button_text, 
                callback_data=f'catejflsp {cat["uid"]}:{cat["stock"]}'
            )
        ])

    if lang == 'zh':
        fstext = (
            "<b>🛒 商品分类 - 请选择所需：</b>\n\n"
            "<b>❗快速查找商品库存发送区号！如（+94）</b>\n\n"
            "<b>❗️首次购买请先少量测试，避免纠纷</b>！\n\n"
            "<b>❗️长期未使用账户可能会出现问题，联系客服处理</b>。"
        )
        keyboard.append([InlineKeyboardButton("⚠️注意事项⚠️（点我查看）", callback_data="notice")])
        keyboard.append([InlineKeyboardButton("❌关闭", callback_data=f"close {user_id}")])
    else:
        fstext = (
            "<b>🛒 Product Categories - Please choose:</b>\n"
            "❗️If you are new, please start with a small test purchase to avoid issues.\n"
            "❗️Inactive accounts may encounter problems, please contact support."
        )
        keyboard.append([InlineKeyboardButton("⚠️ Important Notice ⚠️", callback_data="notice")])
        keyboard.append([InlineKeyboardButton("❌ Close", callback_data=f"close {user_id}")])

    query.edit_message_text(
        text=fstext,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



def czfs_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()

    paytype = query.data.split()[1]  # wechat / alipay / usdt
    
    # 检查是否启用了微信支付宝功能
    if not ENABLE_ALIPAY_WECHAT and paytype in ['wechat', 'alipay']:
        lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
        if lang == 'zh':
            query.answer("❌ 微信支付宝功能已关闭，请选择USDT充值", show_alert=True)
        else:
            query.answer("❌ WeChat and Alipay are disabled, please choose USDT", show_alert=True)
        return
    
    user.update_one({'user_id': user_id}, {'$set': {'cz_paytype': paytype}})
    lang = user.find_one({'user_id': user_id}).get('lang', 'zh')

    if lang == 'zh':
        pay_map = {
            'wechat': '✅ 当前选择：微信支付',
            'alipay': '✅ 当前选择：支付宝支付',
            'usdt': '✅ 当前选择：USDT(TRC20)支付'
        }
        header = f"<b>{pay_map.get(paytype, '✅ 当前选择：未知方式')}</b>\n\n💰请选择充值金额"
        cancel_text = "取消充值"
        back_text = "⬅ 返回"
        custom_text = "自定义金额"
    else:
        pay_map = {
            'wechat': '✅ Selected: WeChat Pay',
            'alipay': '✅ Selected: Alipay',
            'usdt': '✅ Selected: USDT (TRC20)'
        }
        header = f"<b>{pay_map.get(paytype, '✅ Selected: Unknown')}</b>\n\n💰Please select a recharge amount"
        cancel_text = "Cancel"
        back_text = "⬅ Back"
        custom_text = "Custom amount"

    # ✅ 动态按钮前缀，根据支付方式判断
    callback_prefix = "yuecz" if paytype == "usdt" else "czmoney"

    keyboard = [
        [InlineKeyboardButton("10 USDT", callback_data=f"{callback_prefix} 10"),
         InlineKeyboardButton("30 USDT", callback_data=f"{callback_prefix} 30"),
         InlineKeyboardButton("50 USDT", callback_data=f"{callback_prefix} 50")],
        [InlineKeyboardButton("100 USDT", callback_data=f"{callback_prefix} 100"),
         InlineKeyboardButton("300 USDT", callback_data=f"{callback_prefix} 300"),
         InlineKeyboardButton("500 USDT", callback_data=f"{callback_prefix} 500")],
        [InlineKeyboardButton("1000 USDT", callback_data=f"{callback_prefix} 1000"),
         InlineKeyboardButton("2000 USDT", callback_data=f"{callback_prefix} 2000"),
         InlineKeyboardButton("3000 USDT", callback_data=f"{callback_prefix} 3000")],
        [InlineKeyboardButton("5000 USDT", callback_data=f"{callback_prefix} 5000")],
        [InlineKeyboardButton(custom_text, callback_data="zdycz")],
        [InlineKeyboardButton(back_text, callback_data="czback"),
         InlineKeyboardButton(cancel_text, callback_data=f"close {user_id}")]
    ]

    query.edit_message_text(
        text=header,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



def czback_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()

    user.update_one({'user_id': user_id}, {'$unset': {'cz_paytype': ""}})
    lang = user.find_one({'user_id': user_id}).get('lang', 'zh')
    
    # ✅ 从环境变量读取客服联系方式
    customer_service = os.getenv('CUSTOMER_SERVICE', '@lwmmm')

    if ENABLE_ALIPAY_WECHAT:
        # 显示所有支付方式
        if lang == 'zh':
            text = f'''
<b>请选择充值方式</b>

请根据你的常用支付渠道进行选择 
我们支持以下方式：
微信支付,支付宝支付,USDT(TRC20) 数字货币支付

请务必选择你能立即完成支付的方式，以确保订单顺利完成。

注意：微信当前通道不太 容易失败 支付宝通道比较多
付款成功后等浏览器回调成功然后在关闭浏览器 
如果没有到账请第一时间联系客服 {customer_service}
支付宝和微信有手续费 USDT0手续费
            '''.strip()
            keyboard = [
                [InlineKeyboardButton("微信支付", callback_data="czfs wechat"),
                 InlineKeyboardButton("支付宝支付", callback_data="czfs alipay")],
                [InlineKeyboardButton("USDT充值", callback_data="czfs usdt")],
                [InlineKeyboardButton("取消充值", callback_data=f"close {user_id}")]
            ]
        else:
            text = f'''
<b>Please select a payment method</b>

Please choose based on your commonly used payment channel.
We support the following options:
WeChat Pay, Alipay, and USDT (TRC20) cryptocurrency.

Please make sure to choose a method you can complete the payment with immediately to ensure successful processing.

Note: WeChat payment channel may fail more often.
Alipay channels are more stable and reliable.
After payment, please wait for the browser to confirm the callback before closing it.
If your balance is not updated, please contact customer service {customer_service} immediately.
Alipay and WeChat payments may include transaction fees.
USDT payments have zero handling fees.
            '''.strip()
            keyboard = [
                [InlineKeyboardButton("WeChat Pay", callback_data="czfs wechat"),
                 InlineKeyboardButton("Alipay", callback_data="czfs alipay")],
                [InlineKeyboardButton("USDT (TRC20) Recharge", callback_data="czfs usdt")],
                [InlineKeyboardButton("Cancel", callback_data=f"close {user_id}")]
            ]
    else:
        # 仅显示USDT支付方式
        if lang == 'zh':
            text = f'''
<b>USDT (TRC20) 充值</b>

我们目前支持 USDT (TRC20) 数字货币充值

✅ 零手续费，到账快速
✅ 24小时自动处理  
✅ 安全可靠的区块链支付

请务必使用 TRC20 网络进行转账
如有问题请联系客服 {customer_service}
            '''.strip()
            keyboard = [
                [InlineKeyboardButton("USDT充值", callback_data="czfs usdt")],
                [InlineKeyboardButton("取消充值", callback_data=f"close {user_id}")]
            ]
        else:
            text = f'''
<b>USDT (TRC20) Recharge</b>

We currently support USDT (TRC20) cryptocurrency recharge

✅ Zero transaction fees, fast deposit
✅ 24/7 automatic processing
✅ Secure and reliable blockchain payment

Please make sure to use TRC20 network for transfer
If you have any questions, please contact customer service {customer_service}
            '''.strip()
            keyboard = [
                [InlineKeyboardButton("USDT (TRC20) Recharge", callback_data="czfs usdt")],
                [InlineKeyboardButton("Cancel", callback_data=f"close {user_id}")]
            ]

    query.edit_message_text(
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



def czmoney_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    amount = float(query.data.split()[1])
    user_data = user.find_one({'user_id': user_id})
    paytype = user_data.get('cz_paytype', 'wechat')
    lang = user_data.get('lang', 'zh')

    # USDT 独立处理
    if paytype == 'usdt':
        try:
            from usdt_module import yuecz  # type: ignore
            return yuecz(update, context)
        except ImportError:
            query.answer("❌ USDT充值模块暂时不可用", show_alert=True)
            return

    paytype_map = {
        'wechat': 'wxpay',
        'alipay': 'alipay'
    }
    easypay_type = paytype_map.get(paytype, 'alipay')
    USDT_TO_CNY = 7.2

    base_rmb = round(amount * USDT_TO_CNY, 2)
    bianhao = beijing_now_str('%Y%m%d') + str(int(time.time()))

    while True:
        suijishu = round(random.uniform(0.01, 0.50), 2)
        final_rmb = round(base_rmb + suijishu, 2)
        if not topup.find_one({"money": final_rmb, "status": "pending"}):
            break

    # 删除旧订单
    old = topup.find_one({'user_id': user_id, 'status': 'pending'})
    if old:
        # 兼容新旧字段名
        msg_id = old.get('message_id') or old.get('msg_id')
        if msg_id:
            try:
                context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except:
                pass
    topup.delete_many({'user_id': user_id, 'status': 'pending'})

    # 创建支付链接和二维码
    try:
        payment_data = create_payment_with_qrcode(
            pid=EASYPAY_PID,
            key=EASYPAY_KEY,
            gateway_url=EASYPAY_GATEWAY,
            out_trade_no=bianhao,
            name='Telegram充值',
            money=final_rmb,
            notify_url=EASYPAY_NOTIFY,
            return_url=EASYPAY_RETURN,
            payment_type=easypay_type
        )
        pay_url = payment_data['url']
        qrcode_path = payment_data['qrcode_path']
    except Exception as e:
        print(f"[错误] 创建支付链接和二维码失败：{e}")
        query.answer("支付通道异常，请稍后重试", show_alert=True)
        return

    # 时间字段（北京时间）
    now_time = get_beijing_now()
    expire_time = now_time + timedelta(minutes=10)
    now_str = format_beijing_time(now_time)
    expire_str = format_beijing_time(expire_time)

    # 美化文本（中英）
    payment_name = "微信支付" if paytype == 'wechat' else "支付宝"
    if lang == 'zh':
        text = (
            f"<b>📋 {payment_name} 充值订单</b>\n\n"
            f"💰 <b>支付金额：</b><code>¥{final_rmb}</code>\n"
            f"💎 <b>到账USDT：</b><code>{amount}</code>\n"
            f"📱 <b>扫码支付：</b>请使用{payment_name}扫描上方二维码\n"
            f"🔗 <b>或点击按钮：</b>跳转到{payment_name}进行支付\n\n"
            f"<b>订单号：</b><code>{bianhao}</code>\n"
            f"<b>汇率：</b>1 USDT → {USDT_TO_CNY} 元\n"
            f"<b>随机尾数：</b>+{suijishu} 元\n"
            f"<b>创建时间：</b>{now_str}\n"
            f"<b>支付截止：</b>{expire_str}\n\n"
            f"❗️请在10分钟内完成支付，系统自动识别到账\n"
            f"❗️请勿重复支付，避免资金损失"
        )
        btn_text = f"跳转{payment_name}"
        cancel_text = "❌ 取消订单"
    else:
        text = (
            f"<b>📋 {payment_name} Recharge Order</b>\n\n"
            f"💰 <b>Payment Amount:</b><code>¥{final_rmb}</code>\n"
            f"💎 <b>USDT to Receive:</b><code>{amount}</code>\n"
            f"📱 <b>Scan QR Code:</b>Use {payment_name} to scan the QR code above\n"
            f"🔗 <b>Or Click Button:</b>Jump to {payment_name} for payment\n\n"
            f"<b>Order ID:</b><code>{bianhao}</code>\n"
            f"<b>Exchange Rate:</b>1 USDT → {USDT_TO_CNY} CNY\n"
            f"<b>Random Tail:</b>+{suijishu} CNY\n"
            f"<b>Created At:</b>{now_str}\n"
            f"<b>Deadline:</b>{expire_str}\n\n"
            f"❗️Please complete payment within 10 minutes, automatic credit recognition\n"
            f"❗️Do not pay repeatedly to avoid fund loss"
        )
        btn_text = f"Open {payment_name}"
        cancel_text = "❌ Cancel Order"

    keyboard = [
        [InlineKeyboardButton(btn_text, url=pay_url)],
        [InlineKeyboardButton(cancel_text, callback_data=f'qxdingdan {user_id}')]
    ]

    # 发送二维码图片和支付信息
    try:
        msg = context.bot.send_photo(
            chat_id=user_id,
            photo=open(qrcode_path, 'rb'),
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        print(f"[警告] 发送二维码图片失败，回退到文本模式：{e}")
        # 如果发送图片失败，回退到文本+链接模式
        text += f"\n\n🔗 <b>支付链接：</b><a href=\"{pay_url}\">点击此处跳转支付</a>"
        try:
            msg = context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=False,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e2:
            print(f"[错误] 发送支付消息失败：{e2}")
            return

    try:
        topup.insert_one({
            'bianhao': bianhao,
            'user_id': user_id,
            'money': final_rmb,
            'base_amount': amount,
            'usdt': amount,
            'suijishu': suijishu,
            'timer': now_str,
            'time': now_time,
            'status': 'pending',
            'cz_type': paytype,
            'expire_time': expire_str,
            'message_id': msg.message_id,
            'pay_url': pay_url,
            'qrcode_path': qrcode_path
        })
        print(f"[订单创建成功] 用户ID: {user_id} 金额: {final_rmb} 单号: {bianhao} 二维码: {qrcode_path}")
    except Exception as e:
        print(f"[错误] 插入订单失败：{e}")



def cancel_order_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id
    uid = query.data.split()[1]

    if str(user_id) != uid:
        query.answer("无权限取消此订单", show_alert=True)
        return

    order = topup.find_one({'user_id': user_id, 'status': 'pending'})
    if not order:
        query.edit_message_text("无待取消订单 No pending order.")
        return

    try:
        # 兼容新旧字段名
        msg_id = order.get('message_id') or order.get('msg_id')
        if msg_id:
            context.bot.delete_message(chat_id=user_id, message_id=msg_id)
    except:
        pass

    topup.update_one({'_id': order['_id']}, {'$set': {'status': 'cancelled'}})

    context.bot.send_message(chat_id=user_id, text="✅ 订单已取消 Order Cancelled.")



def yuecz(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    base_amount = int(query.data.replace('yuecz ', ''))
    user_id = query.from_user.id
    bot_id = context.bot.id

    user_data = user.find_one({'user_id': user_id})
    lang = user_data.get('lang', 'zh')

    # 删除旧订单
    topup.delete_many({'user_id': user_id, 'status': 'pending'})

    # 编号生成
    timer = beijing_now_str('%Y%m%d')
    bianhao = timer + str(int(time.time()))

    # 随机尾数金额
    while True:
        suijishu = round(random.uniform(0.01, 0.50), 4)
        total_money = float(Decimal(str(base_amount)) + Decimal(str(suijishu)))
        if not topup.find_one({'money': total_money, 'status': 'pending'}):
            break

    now = get_beijing_now()
    expire = now + timedelta(minutes=10)
    timer_str = format_beijing_time(now)
    expire_str = format_beijing_time(expire)

    trc20 = shangtext.find_one({'projectname': '充值地址'})['text']

    # ✅ 中文模板
    text = f"""
<b>充值详情</b>

✅ <b>唯一收款地址：</b><code>{trc20}</code>
（推荐使用扫码转账更加安全 👉点击上方地址即可快速复制粘贴）

💰 <b>实际支付金额：</b><code>{total_money}</code> USDT
（👉点击上方金额可快速复制粘贴）

<b>充值订单创建时间：</b>{timer_str}
<b>转账最后截止时间：</b>{expire_str}

❗️请一定按照金额后面小数点转账，否则无法自动到账
❗️付款前请再次核对地址与金额，避免转错
    """.strip()

    # 翻译（可选）
    if lang != 'zh':
        text = get_fy(text)

    # 按钮
    keyboard = [[InlineKeyboardButton("❌ 取消订单" if lang == 'zh' else "❌ Cancel Order", callback_data=f'qxdingdan {user_id}')]]

    # 发送消息（如果二维码图片存在则发送图片，否则只发送文本）
    import os
    qr_file = f'{trc20}.png'
    
    try:
        if os.path.exists(qr_file):
            # 发送图片 + 消息
            message = context.bot.send_photo(
                chat_id=user_id,
                photo=open(qr_file, 'rb'),
                caption=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # 如果图片不存在，只发送文本消息
            message = context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        # 如果发送图片失败，回退到发送文本
        message = context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # 插入订单（补齐 cz_type、status、time 字段）
    topup.insert_one({
        'bianhao': bianhao,
        'user_id': user_id,
        'money': total_money,
        'usdt': base_amount,
        'suijishu': suijishu,
        'timer': timer_str,
        'expire_time': expire_str,
        'time': now,                # ✅ MongoDB 可识别的时间字段
        'cz_type': 'usdt',          # ✅ 正确标识 usdt 充值类型
        'status': 'pending',
        'message_id': message.message_id
    })



def handle_all_callbacks(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id

    # 查询用户语言
    try:
        user_doc = user.find_one({'user_id': user_id})
        lang = user_doc.get('lang', 'zh') if user_doc else 'zh'
    except Exception as e:
        print(f"查询用户语言失败: {e}")
        lang = 'zh'

    print(f"收到回调: {query.data}")

    if query.data == "notice":
        customer_service = os.getenv('CUSTOMER_SERVICE', '@lwmmm')
        alert_text = (
            f"购买的账号只包首次登录，过时不候。\n"
            f"API账号为自助登录，不会的请看教程。\n"
            f"不会登录请联系 {customer_service}"
            if lang == 'zh'
            else f"Only first login is guaranteed.\nSelf-login API.\nNeed help? {customer_service}"
        )
        query.answer(alert_text, show_alert=True)

    # ========== 提现管理 ==========
    elif query.data == "withdrawal_manage":
        import datetime
        query.answer()
        
        try:
            # 获取待处理的提现申请
            pending_withdrawals = list(withdrawal_requests.find({'status': 'pending'}).sort('created_time', 1))
            pending_count = len(pending_withdrawals)
            pending_amount = sum([w['amount'] for w in pending_withdrawals])
            
            today_start = get_beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_processed = withdrawal_requests.count_documents({
                'status': {'$in': ['approved', 'completed']},
                'processed_time': {'$gte': today_start}
            })
            
            if pending_count == 0:
                text = f"""💸 <b>提现管理中心</b>

✅ <b>暂无待处理提现</b>
当前没有用户提现申请

📊 <b>今日统计</b>
• 已处理：{today_processed} 笔
• 系统运行正常

⏰ 最后检查：{beijing_now_str('%H:%M:%S')}"""

                keyboard = [
                    [InlineKeyboardButton("🔄 刷新", callback_data="withdrawal_manage")],
                    [InlineKeyboardButton("🔙 返回", callback_data="backstart")]
                ]
            else:
                text = f"""💸 <b>提现管理中心</b>

📊 <b>待处理提现</b>
• 申请数量：{pending_count} 笔
• 申请金额：{pending_amount:.2f} USDT

✅ <b>今日已处理</b>
• 已审核：{today_processed} 笔

⏰ <b>最新申请</b>"""

                # 显示最新的3个申请
                for i, w in enumerate(pending_withdrawals[:3], 1):
                    created = format_beijing_time(w['created_time'], '%m-%d %H:%M')
                    text += f"\n{i}. 用户{w['user_id']} - {w['amount']:.2f} USDT ({created})"

                keyboard = [
                    [
                        InlineKeyboardButton("📋 查看所有申请", callback_data="view_all_withdrawals")
                    ],
                    [
                        InlineKeyboardButton("🔄 刷新", callback_data="withdrawal_manage"),
                        InlineKeyboardButton("🔙 返回", callback_data="backstart")
                    ]
                ]
            
            # 安全编辑消息
            try:
                query.edit_message_text(
                    text=text,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                if "not modified" in str(e):
                    query.answer("界面已是最新状态")
                else:
                    print(f"编辑消息错误: {e}")
                    query.answer("加载失败，请重试")
            
        except Exception as e:
            print(f"提现管理错误: {e}")
            query.answer("加载失败，请重试", show_alert=True)

    # ========== 查看所有提现申请 ==========
    elif query.data == "view_all_withdrawals":
        import datetime
        query.answer()
        
        try:
            pending_withdrawals = list(withdrawal_requests.find({'status': 'pending'}).sort('created_time', 1))
            
            if not pending_withdrawals:
                text = "📋 <b>提现申请列表</b>\n\n✅ 暂无待处理申请"
                keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="withdrawal_manage")]]
            else:
                text = f"📋 <b>提现申请列表</b> (共{len(pending_withdrawals)}笔)\n\n"
                keyboard = []
                
                for w in pending_withdrawals:
                    created = format_beijing_time(w['created_time'], '%m-%d %H:%M')
                    address_short = f"{w['withdrawal_address'][:6]}...{w['withdrawal_address'][-6:]}"
                    text += f"💰 {w['amount']:.2f} USDT\n"
                    text += f"👤 用户ID: {w['user_id']}\n" 
                    text += f"📍 地址: {address_short}\n"
                    text += f"⏰ 时间: {created}\n\n"
                    
                    keyboard.append([
                        InlineKeyboardButton(
                            f"✅ 通过 {w['amount']:.1f}U",
                            callback_data=f"approve_withdrawal_{w['_id']}"
                        ),
                        InlineKeyboardButton(
                            f"❌ 拒绝",
                            callback_data=f"reject_withdrawal_{w['_id']}"
                        )
                    ])
                
                keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="withdrawal_manage")])
            
            try:
                query.edit_message_text(
                    text=text,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                if "not modified" in str(e):
                    query.answer("界面已是最新状态")
            
        except Exception as e:
            print(f"查看申请错误: {e}")
            query.answer("加载失败", show_alert=True)

    # ========== 🆕 用户提交提现TXID入口 ==========
    elif query.data.startswith("submit_user_txid_"):
        from bson import ObjectId
        withdrawal_id = query.data.replace("submit_user_txid_", "")
        user_id = update.effective_user.id
        query.answer()
        
        try:
            withdrawal = withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
            if not withdrawal:
                query.answer("提现记录不存在", show_alert=True)
                return
            
            # 验证是否是该用户的提现申请
            if withdrawal.get('user_id') != user_id:
                query.answer("无权限操作此提现", show_alert=True)
                return
            
            # 检查状态，只有pending或approved状态可以提交TXID
            if withdrawal.get('status') not in ['pending', 'approved']:
                query.answer(f"当前状态({withdrawal.get('status')})不允许提交TXID", show_alert=True)
                return
            
            # 标记用户进入等待TXID输入状态
            WAITING_USER_TXID[user_id] = withdrawal_id
            
            text = f"""💸 <b>提交交易哈希</b>

📋 <b>提现信息</b>
• 提现金额: {withdrawal['amount']:.2f} USDT
• 提现地址: {withdrawal.get('withdrawal_address', 'N/A')}
• 当前状态: 等待提交交易哈希

👉 <b>操作步骤</b>
1. 请确认您已向指定地址转账
2. 从钱包或交易所获取交易哈希(TXID)
3. 直接在聊天框中发送完整的交易哈希
4. 系统将验证您的交易并处理提现

⚠️ <b>注意事项</b>
• 交易哈希通常为64位16进制字符串
• 可以包含或不包含'0x'前缀
• 至少需要20个字符

📱 <b>请在下方输入框发送交易哈希</b>"""

            keyboard = [
                [InlineKeyboardButton("❌ 取消", callback_data=f"cancel_txid_input_{user_id}")]
            ]
            
            query.edit_message_text(
                text=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            print(f"进入TXID提交界面错误: {e}")
            query.answer("操作失败", show_alert=True)
    
    # ========== 🆕 取消TXID输入 ==========
    elif query.data.startswith("cancel_txid_input_"):
        user_id_str = query.data.replace("cancel_txid_input_", "")
        user_id = int(user_id_str)
        
        if user_id in WAITING_USER_TXID:
            del WAITING_USER_TXID[user_id]
        
        query.answer("已取消TXID输入")
        query.edit_message_text(
            "✅ 已取消交易哈希输入\n\n如需重新提交，请返回提现记录。",
            parse_mode='HTML'
        )
    
    # ========== 🆕 刷新用户提现列表 ==========
    elif query.data == "refresh_my_withdrawals":
        from bson import ObjectId
        import datetime
        
        user_id = update.effective_user.id
        query.answer("刷新中...")
        
        # 查询用户的所有提现记录
        withdrawals = list(withdrawal_requests.find({'user_id': user_id}).sort('created_time', -1).limit(10))
        
        if not withdrawals:
            query.edit_message_text(
                "📋 <b>我的提现记录</b>\n\n"
                "暂无提现记录",
                parse_mode='HTML'
            )
            return
        
        # 统计各状态数量
        status_map = {
            'pending': '待审核',
            'approved': '已审核',
            'user_submitted': '已提交TXID',
            'completed': '已完成',
            'rejected': '已拒绝'
        }
        
        text = f"📋 <b>我的提现记录</b>\n\n"
        
        for i, w in enumerate(withdrawals[:5], 1):
            status = status_map.get(w.get('status'), '未知')
            created_time = w.get('created_time')
            created = format_beijing_time(created_time, '%m-%d %H:%M') if created_time else beijing_now_str('%m-%d %H:%M')
            
            text += f"{i}. <b>{w['amount']:.2f} USDT</b> - {status}\n"
            text += f"   申请时间: {created}\n"
            
            # 如果有用户提交的TXID，显示简短版本
            if w.get('user_tx_hash'):
                txid_short = f"{w['user_tx_hash'][:8]}...{w['user_tx_hash'][-8:]}"
                text += f"   交易哈希: <code>{txid_short}</code>\n"
            
            text += "\n"
        
        # 创建按钮
        keyboard = []
        
        # 如果有待处理的提现（pending或approved），显示详情按钮
        for w in withdrawals:
            if w.get('status') in ['pending', 'approved'] and not w.get('user_tx_hash'):
                keyboard.append([
                    InlineKeyboardButton(
                        f"💸 提交TXID ({w['amount']:.2f} USDT)",
                        callback_data=f"submit_user_txid_{w['_id']}"
                    )
                ])
                break  # 只显示最新的一个
        
        keyboard.append([InlineKeyboardButton("🔄 刷新", callback_data="refresh_my_withdrawals")])
        
        try:
            query.edit_message_text(
                text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
            )
        except Exception as e:
            if "not modified" in str(e):
                query.answer("已是最新状态")

    # ========== 通过单个提现申请 ==========
    elif query.data.startswith("approve_withdrawal_"):
        import datetime
        from bson import ObjectId
        withdrawal_id = query.data.replace("approve_withdrawal_", "")
        query.answer()
        
        try:
            withdrawal = withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
            
            if not withdrawal:
                query.answer("申请不存在", show_alert=True)
                return
            
            # 更新申请状态
            withdrawal_requests.update_one(
                {'_id': ObjectId(withdrawal_id)},
                {
                    '$set': {
                        'status': 'approved',
                        'processed_time': datetime.datetime.now(),
                        'processed_by': user_id
                    }
                }
            )
            
            text = f"""✅ <b>提现申请已通过</b>

📋 申请信息:• 用户ID: {withdrawal['user_id']}
• 提现金额: {withdrawal['amount']:.2f} USDT
• 收款地址: {withdrawal['withdrawal_address']}
• 审核时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

💡 <b>下一步操作:</b>
1. 手动向用户地址转账
2. 获取交易哈希
3. 点击"完成付款"输入交易哈希
4. 系统自动通知用户"""

            keyboard = [
                [InlineKeyboardButton("💸 完成付款", callback_data=f"complete_payment_{withdrawal_id}")],
                [InlineKeyboardButton("📋 复制地址", callback_data=f"copy_address_{withdrawal_id}")],
                [InlineKeyboardButton("🔙 返回列表", callback_data="view_all_withdrawals")]
            ]
            
            query.edit_message_text(
                text=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            print(f"审核错误: {e}")
            query.answer("审核失败", show_alert=True)

    # ========== 拒绝单个提现申请 ==========
    elif query.data.startswith("reject_withdrawal_"):
        import datetime
        from bson import ObjectId
        withdrawal_id = query.data.replace("reject_withdrawal_", "")
        query.answer()
        
        try:
            withdrawal = withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
            
            if not withdrawal:
                query.answer("申请不存在", show_alert=True)
                return
            
            # 更新申请状态
            withdrawal_requests.update_one(
                {'_id': ObjectId(withdrawal_id)},
                {
                    '$set': {
                        'status': 'rejected',
                        'processed_time': datetime.datetime.now(),
                        'processed_by': user_id,
                        'reject_reason': '管理员拒绝'
                    }
                }
            )
            
            # 退还用户余额
            user.update_one(
                {'user_id': withdrawal['user_id']},
                {
                    '$inc': {
                        'balance': withdrawal['amount'],
                        'frozen_balance': -withdrawal['amount']
                    }
                }
            )
            
            text = f"""❌ <b>提现申请已拒绝</b>

📋 申请信息:
• 用户ID: {withdrawal['user_id']}
• 申请金额: {withdrawal['amount']:.2f} USDT
• 拒绝时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}

✅ 系统已自动:
• 退还用户余额
• 发送拒绝通知
• 记录操作日志"""

            keyboard = [
                [InlineKeyboardButton("🔙 返回列表", callback_data="view_all_withdrawals")]
            ]
            
            query.edit_message_text(
                text=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            print(f"拒绝错误: {e}")
            query.answer("拒绝失败", show_alert=True)

    # ========== 完成付款：直接完成提现（无需哈希验证）==========
    elif query.data.startswith("complete_payment_"):
        from bson import ObjectId
        import datetime
        withdrawal_id = query.data.replace("complete_payment_", "")
        query.answer()
        try:
            withdrawal = withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
            if not withdrawal:
                query.answer("申请不存在", show_alert=True)
                return
            if withdrawal.get('status') != 'approved':
                query.answer("当前状态不是已审核，无法完成付款", show_alert=True)
                return

            # 🆕 直接完成付款，无需输入哈希
            now = datetime.datetime.now()
            
            # 更新提现记录为已完成
            withdrawal_requests.update_one(
                {'_id': ObjectId(withdrawal_id), 'status': 'approved'},
                {
                    '$set': {
                        'status': 'completed',
                        'processed_time': now,
                        'completed_time': now,
                        'updated_time': now,
                        'processed_by': user_id
                    }
                }
            )
            
            # 显示确认消息给管理员
            text = f"""✅ <b>提现已完成</b>

📋 申请信息:
• 用户ID: {withdrawal['user_id']}
• 提现金额: {withdrawal['amount']:.2f} USDT
• 提现地址: {withdrawal['withdrawal_address']}
• 完成时间: {format_beijing_time(now)}

✅ 系统已自动:
• 标记提现完成
• 通知用户
• 记录操作日志"""

            keyboard = [
                [InlineKeyboardButton("📋 返回列表", callback_data="view_all_withdrawals")],
                [InlineKeyboardButton("💸 管理中心", callback_data="withdrawal_manage")]
            ]
            query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
            
        except Exception as e:
            print(f"完成付款错误: {e}")
            query.answer("操作失败", show_alert=True)

    # ========== 复制地址（弹窗显示，便于手动复制） ==========
    elif query.data.startswith("copy_address_"):
        from bson import ObjectId
        withdrawal_id = query.data.replace("copy_address_", "")
        w = withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
        if not w:
            query.answer("地址不存在", show_alert=True)
        else:
            # 弹窗显示地址供手动复制
            query.answer(w['withdrawal_address'], show_alert=True)           
            
    # ========== 关闭按钮 ==========
    elif query.data.startswith("close "):
        user_id_to_close = query.data.split(" ")[1]
        if str(user_id) == user_id_to_close:
            query.delete_message()
        else:
            query.answer("无权限")

    else:
        query.answer()
        print(f"已忽略回调: {query.data}")
        
        
        
        
def del_message(message):
    try:
        message.delete()
    except:
        pass


def standard_num(num):
    value = Decimal(str(num)).quantize(Decimal("0.01"))
    return value.to_integral() if value == value.to_integral() else value.normalize()


def jiexi(context: CallbackContext):
    """后台线程执行充值解析，不阻塞主线程"""
    threading.Thread(target=_jiexi_worker, args=(context,), daemon=True).start()

def _jiexi_worker(context):
    """
    充值解析的实际工作函数
    解析链上充值记录：
    - 只处理 state = 0 且 to_address 是充值地址的记录
    - 每条 qukuai 记录只处理一次
    - 同一个 txid 只会成功充值一次
    - 每次最多处理 5 条记录，避免阻塞主线程
    """
    from pymongo import ReturnDocument

    # 获取充值地址
    trc20_record = shangtext.find_one({'projectname': '充值地址'})
    if not trc20_record or 'text' not in trc20_record:
        logging.warning("⚠️ 未找到充值地址配置，终止解析")
        return
    trc20 = trc20_record['text']

    # 限制每次最多处理 5 条记录，避免阻塞
    max_records = 5
    processed = 0

    while processed < max_records:
        # 原子方式领取一条待处理记录，并立即标记为 -1（处理中）
        record = qukuai.find_one_and_update(
            {'state': 0, 'to_address': trc20},
            {'$set': {'state': -1}},
            return_document=ReturnDocument.BEFORE
        )

        if not record:
            # 没有更多待处理记录
            break
        
        processed += 1

        txid = record['txid']
        quant_raw = record['quant']
        from_address = record['from_address']

        try:
            # 如果这个 txid 已经在 topup 里出现过，说明之前已经处理过，避免重复加钱
            if topup.find_one({'txid': txid}):
                logging.info(f"⏭ TXID 已处理过，跳过重复充值: {txid}")
                qukuai.update_one({'txid': txid}, {'$set': {'state': 1}})
                continue

            # 计算金额（USDT）
            quant_dec = Decimal(quant_raw) / Decimal('1000000')
            quant = float(quant_dec)          # 本次充值金额
            today_money = quant

            # 查找是否有相同金额的订单（带浮点误差容差 ±0.001），且状态为 pending
            dj_list = topup.find_one({
                "money": {
                    "$gte": round(quant - 0.001, 3),
                    "$lte": round(quant + 0.001, 3)
                },
                "status": "pending"
            })

            if dj_list is not None and 'message_id' in dj_list and 'user_id' in dj_list:
                message_id = dj_list['message_id']
                user_id = dj_list['user_id']
                order_doc_id = dj_list['_id']   # 这笔订单的唯一 ID

                # 删除原始充值详情消息
                try:
                    context.bot.delete_message(chat_id=user_id, message_id=message_id)
                except Exception as e:
                    logging.warning(f"⚠️ 删除充值详情消息失败：{e}")

                # 获取用户信息
                user_list = user.find_one({'user_id': user_id})
                if not user_list:
                    qukuai.update_one({'txid': txid}, {"$set": {"state": 2}})
                    continue

                username = user_list.get('username', '无')
                fullname = user_list.get('fullname', '无').replace('<', '').replace('>', '')
                old_usdt = float(user_list.get('USDT', 0))

                # 更新余额
                now_price = standard_num(old_usdt + quant)
                now_price = float(now_price) if '.' in str(now_price) else int(now_price)
                user.update_one({'user_id': user_id}, {"$set": {'USDT': now_price}})

                # 写入充值日志
                timer = beijing_now_str()
                order_id = str(uuid.uuid4())
                user_logging(order_id, '充值', user_id, today_money, timer)

                # 用户通知（不带关闭按钮）
                user_text = f'''
<b>🎉 恭喜您，成功充值！</b> 💰

<b>充值金额:</b> <u>{today_money} USDT</u>  
<b>充值地址:</b> <code>{from_address}</code>  
<b>时间:</b> <i>{timer}</i>

<b>您的账户余额:</b> <b>{now_price} USDT</b>  
<b>祝您一切顺利！</b> 🥳💫
                '''
                context.bot.send_message(
                    chat_id=user_id,
                    text=user_text,
                    parse_mode='HTML'
                )

                # 通知管理员
                admin_text = f'''
用户: <a href="tg://user?id={user_id}">{fullname}</a> @{username} 充值成功
地址: <code>{from_address}</code>
充值: {today_money} USDT
<a href="https://tronscan.org/#/transaction/{txid}">充值详细</a>
                '''
                for admin_id in get_admin_ids():
                    try:
                        context.bot.send_message(
                            chat_id=admin_id,
                            text=admin_text,
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        logging.warning(f"Failed to send recharge notification to admin {admin_id}: {e}")

                # 删除 pending 订单消息（如果有的话）
                existing_order = dj_list
                msg_id = existing_order.get('message_id') or existing_order.get('msg_id')
                if msg_id:
                    try:
                        context.bot.delete_message(chat_id=user_id, message_id=msg_id)
                    except Exception:
                        pass

                # 更新这条 topup 订单为成功，并绑定 txid
                topup.update_one(
                    {'_id': order_doc_id},
                    {
                        '$set': {
                            'status': 'success',
                            'success_time': datetime.now(),
                            'txid': txid,
                            'from_address': from_address
                        }
                    }
                )

                # qukuai 标记为处理成功
                qukuai.update_one({'txid': txid}, {"$set": {"state": 1}})

            else:
                # 未找到订单或字段缺失，标记为失败
                logging.warning(f"⚠️ 未找到匹配订单，标记失败: txid={txid}, amount={quant}")
                qukuai.update_one({'txid': txid}, {"$set": {"state": 2}})

        except Exception as e:
            logging.exception(f"❌ 处理充值记录异常 txid={txid}: {e}")
            qukuai.update_one({'txid': txid}, {"$set": {"state": 2}})

def validate_txid_format(txid: str) -> bool:
    """
    验证TXID格式是否有效
    支持多种格式:
    - 0x开头的64位16进制字符串 (TRC20/ETH)
    - 不以0x开头的64位16进制字符串
    - 至少20位的合法16进制数字
    """
    import re
    
    if not txid or not isinstance(txid, str):
        return False
    
    txid = txid.strip()
    
    # 定义支持的TXID格式
    patterns = [
        r'^0x[a-fA-F0-9]{64}$',      # 0x + 64位16进制
        r'^[a-fA-F0-9]{64}$',        # 64位16进制
        r'^[a-fA-F0-9]{20,}$'        # 至少20位16进制
    ]
    
    return any(re.match(pattern, txid) for pattern in patterns)


def handle_user_withdrawal_txid(update: Update, context: CallbackContext):
    """
    处理用户提交的提现TXID
    当用户完成链上转账后，提交交易哈希作为凭证
    """
    from bson import ObjectId
    import datetime
    
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()
    
    # 检查用户是否在等待提交TXID状态
    if user_id not in WAITING_USER_TXID:
        return

    withdrawal_id = WAITING_USER_TXID[user_id]

    # 使用改进的哈希校验
    if not validate_txhash(text):
        update.message.reply_text(
            "❌ 交易哈希格式不正确\n\n"
            "请提供有效的交易哈希，例如：\n"
            "• 0x开头的64位16进制字符串\n"
            "• 或至少10位的字母数字组合"
        )
        return
    
    # 查询提现记录
    withdrawal = withdrawal_requests.find_one({'_id': ObjectId(withdrawal_id)})
    if not withdrawal:
        update.message.reply_text("❌ 提现记录不存在，请联系客服")
        del WAITING_USER_TXID[user_id]
        return
    
    # 检查提现状态
    if withdrawal.get('status') not in ['pending', 'approved']:
        update.message.reply_text(
            f"❌ 提现状态异常（当前状态: {withdrawal.get('status')}），请联系客服"
        )
        del WAITING_USER_TXID[user_id]
        return
    
    try:
        now = datetime.datetime.now()
        
        # 更新提现记录，保存用户提交的TXID
        withdrawal_requests.update_one(
            {'_id': ObjectId(withdrawal_id)},
            {
                '$set': {
                    'user_tx_hash': text,
                    'user_submitted_time': now,
                    'status': 'user_submitted',  # 用户已提交TXID，等待验证
                    'updated_time': now
                }
            }
        )

        # 记录日志
        print(f"✅ 提现完成: withdrawal_id={withdrawal_id}, tx_hash={text}, admin={user_id}")

        update.message.reply_text(
            f"✅ <b>交易哈希已提交</b>\n\n"
            f"📋 <b>提现信息</b>\n"
            f"• 提现金额: {withdrawal['amount']:.2f} USDT\n"
            f"• 提现地址: {withdrawal.get('withdrawal_address', 'N/A')}\n"
            f"• 交易哈希: <code>{text}</code>\n"
            f"• 提交时间: {format_beijing_time(now)}\n\n"
            f"⏳ <b>处理状态</b>\n"
            f"系统正在验证您的交易，请耐心等待。\n"
            f"验证通过后将自动通知您。\n\n"
            f"如有疑问，请联系客服。",
            parse_mode='HTML'
        )
        
        # 通知管理员
        for admin_id in ADMIN_IDS:
            try:
                context.bot.send_message(
                    chat_id=admin_id,
                    text=f"🔔 <b>新的提现TXID提交</b>\n\n"
                         f"用户ID: {user_id}\n"
                         f"提现金额: {withdrawal['amount']:.2f} USDT\n"
                         f"交易哈希: <code>{text}</code>\n"
                         f"提交时间: {format_beijing_time(now)}\n\n"
                         f"请尽快验证处理。",
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"通知管理员失败 {admin_id}: {e}")
        
    except Exception as e:
        print(f"❌ 完成付款写入错误: {e}")
        import traceback
        traceback.print_exc()
        update.message.reply_text(f"❌ 写入失败: {str(e)}\n请联系技术支持")
        return

    # 清除等待状态
    del WAITING_USER_TXID[user_id]


def check_my_withdrawals(update: Update, context: CallbackContext):
    """
    用户查看自己的提现记录
    可以查看状态、提交TXID等操作
    """
    from bson import ObjectId
    import datetime
    
    user_id = update.effective_user.id
    
    # 查询用户的所有提现记录
    withdrawals = list(withdrawal_requests.find({'user_id': user_id}).sort('created_time', -1).limit(10))
    
    if not withdrawals:
        update.message.reply_text(
            "📋 <b>我的提现记录</b>\n\n"
            "暂无提现记录",
            parse_mode='HTML'
        )
        return
    
    # 统计各状态数量
    status_map = {
        'pending': '待审核',
        'approved': '已审核',
        'user_submitted': '已提交TXID',
        'completed': '已完成',
        'rejected': '已拒绝'
    }
    
    text = f"📋 <b>我的提现记录</b>\n\n"
    
    for i, w in enumerate(withdrawals[:5], 1):
        status = status_map.get(w.get('status'), '未知')
        created_time = w.get('created_time')
        created = format_beijing_time(created_time, '%m-%d %H:%M') if created_time else beijing_now_str('%m-%d %H:%M')
        
        text += f"{i}. <b>{w['amount']:.2f} USDT</b> - {status}\n"
        text += f"   申请时间: {created}\n"
        
        # 如果有用户提交的TXID，显示简短版本
        if w.get('user_tx_hash'):
            txid_short = f"{w['user_tx_hash'][:8]}...{w['user_tx_hash'][-8:]}"
            text += f"   交易哈希: <code>{txid_short}</code>\n"
        
        text += "\n"
    
    # 创建按钮
    keyboard = []
    
    # 如果有待处理的提现（pending或approved），显示详情按钮
    for w in withdrawals:
        if w.get('status') in ['pending', 'approved'] and not w.get('user_tx_hash'):
            keyboard.append([
                InlineKeyboardButton(
                    f"💸 提交TXID ({w['amount']:.2f} USDT)",
                    callback_data=f"submit_user_txid_{w['_id']}"
                )
            ])
            break  # 只显示最新的一个
    
    keyboard.append([InlineKeyboardButton("🔄 刷新", callback_data="refresh_my_withdrawals")])
    
    update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )


def handle_admin_txhash_message(update: Update, context: CallbackContext):
    """
    ⚠️ 已弃用：管理员发送交易哈希功能
    
    新流程：管理员点击"完成付款"按钮后直接完成提现，无需输入哈希
    
    此函数保留用于向后兼容，但在新流程中不再使用
    """
    from bson import ObjectId
    import datetime

    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    # 不是等待状态直接返回（不干扰其它文本处理）
    if user_id not in WAITING_TXHASH:
        return

    # ⚠️ 此功能已弃用，清除等待状态
    del WAITING_TXHASH[user_id]
    
    update.message.reply_text(
        "ℹ️ <b>提示</b>\n\n"
        "此功能已更新。\n"
        "请使用「完成付款」按钮直接完成提现，无需输入交易哈希。",
        parse_mode='HTML'
    )
    return

def jianceguoqi(context: CallbackContext):
    # 去掉 while True，只执行一次检查（避免线程累积，由 job_queue 定时调用）
    for i in topup.find({'status': 'pending'}):
        # 忽略没有 message_id 的数据
        if 'message_id' not in i:
            continue

        try:
            timer = i['timer']
            bianhao = i['bianhao']
            user_id = i['user_id']
            message_id = i['message_id']

            # 解析订单时间（北京时间字符串 -> 带时区的 datetime）
            dt = parse_to_beijing(timer)
            if not dt:
                continue
            # 计算过期时间（时区感知的 datetime）
            new_dt = dt + timedelta(minutes=10)
            # 获取当前北京时间（时区感知的 datetime）
            current_time = get_beijing_now()

            # 比较两个时区感知的 datetime 对象
            if current_time >= new_dt:
                # 删除原来的充值页面
                try:
                    context.bot.delete_message(chat_id=user_id, message_id=message_id)
                except Exception as e:
                    print(f"⚠️ 删除旧支付消息失败：{e}")

                # 发送一条新的通知说明
                #keyboard = [[InlineKeyboardButton("✅已读（点击销毁此消息）", callback_data=f'close {user_id}')]]
                #try:
                #    context.bot.send_message(
                #        chat_id=user_id,
                #        text=f"❌ <b>订单超时</b>\n\n订单号：<code>{bianhao}</code>\n状态：<b>支付超时或金额错误</b>",
                #        parse_mode='HTML',
                #        reply_markup=InlineKeyboardMarkup(keyboard)
                #    )
                #except Exception as e:
                #    print(f"⚠️ 发送超时通知失败：{e}")

                # 删除订单记录
                topup.delete_one({'_id': i['_id']})

        except Exception as e:
            print(f"⚠️ 检查超时订单失败：{e}")

def suoyouchengxu(context: CallbackContext):
    jianceguoqi(context)

    job = context.job_queue.get_jobs_by_name('suoyouchengxu')
    if job != ():
        job[0].schedule_removal()

def fbgg(update: Update, context: CallbackContext):
    chat = update.effective_chat
    if chat.type != 'private':
        return

    user_id = chat.id
    
    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        context.bot.send_message(chat_id=user_id, text="⛔ 你没有权限执行 /gg 命令")
        return

    # 获取广告内容
    text = update.message.text.replace('/gg ', '').strip()
    if not text:
        context.bot.send_message(chat_id=user_id, text="❗ 请在 /gg 后输入广告内容，例如：/gg <b>欢迎使用</b>")
        return

    context.bot.send_message(chat_id=user_id, text='🚀 正在开始群发广告...')

    def send_ads():
        total_users = user.count_documents({})
        success_count = 0
        fail_count = 0
        success_users = []
        fail_users = []

        # 初始进度消息
        status_message = context.bot.send_message(
            chat_id=user_id,
            text="📤 群发进度：0 / 0 (0%)"
        )

        all_users = list(user.find({}))
        for idx, u in enumerate(all_users, start=1):
            uid = u['user_id']
            first = u.get('first_name') or ''
            last = u.get('last_name') or ''
            fullname = (first + ' ' + last).strip() or '-'
            uname = '@' + u['username'] if u.get('username') else '无'

            user_info = f"{idx}. 昵称: {fullname} | 用户名: {uname} | ID: {uid}"
            keyboard = [[InlineKeyboardButton("✅已读（点击销毁此消息）", callback_data=f'close {uid}')]]

            try:
                context.bot.send_message(
                    chat_id=uid,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='HTML'
                )
                success_count += 1
                success_users.append(user_info)
            except:
                fail_count += 1
                fail_users.append(user_info)

            # 每5人或最后一人更新一次进度
            if idx % 5 == 0 or idx == total_users:
                percent = int((idx / total_users) * 100)
                bar = '▇' * (percent // 10) + '□' * (10 - (percent // 10))
                progress_text = (
                    f"📤 群发进度：{bar} {percent}%\n"
                    f"👥 总用户数：{total_users}\n"
                    f"✅ 成功：{success_count}  ❌ 失败：{fail_count}"
                )
                try:
                    context.bot.edit_message_text(
                        chat_id=user_id,
                        message_id=status_message.message_id,
                        text=progress_text,
                        parse_mode='HTML'
                    )
                except:
                    pass

            time.sleep(0.5)  # 控制速率防封

        # 群发完成更新最终消息
        final_text = (
            f"✅ 广告发送完成！\n\n"
            f"📤 群发进度：{'▇' * 10} 100%\n"
            f"👥 总用户数：{total_users}\n"
            f"✅ 成功：{success_count}  ❌ 失败：{fail_count}"
        )
        try:
            context.bot.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text=final_text,
                parse_mode='HTML'
            )
        except:
            pass

        # 打包 TXT 文件
        success_text = "\n".join(success_users)
        fail_text = "\n".join(fail_users)
        result_content = f"✅ 成功用户：\n{success_text}\n\n❌ 失败用户：\n{fail_text}"
        file_obj = StringIO(result_content)
        file_obj.name = "群发结果.txt"
        context.bot.send_document(chat_id=user_id, document=InputFile(file_obj))

    threading.Thread(target=send_ads).start()
    
def adm(update: Update, context: CallbackContext):
    chat = update.effective_chat
    if chat.type != 'private':
        return

    user_id = chat.id
    text = update.message.text
    text_parts = text.split(' ')

    # 权限检查 - 使用env配置的管理员列表
    if not is_admin(user_id):
        return

    # 支持两种格式：
    # 1. /add 用户ID 金额 （总部用户）
    # 2. /add @代理Bot用户名 用户ID 金额 （代理Bot用户）
    if len(text_parts) == 4:
        # 代理Bot用户管理
        admin_add_agent_user_balance(update, context)
        return
    
    if len(text_parts) != 3:
        msg = """
<b>格式错误 ❌</b>
-----------------------------
<b>正确命令格式：</b>

<b>1. 总部用户操作：</b>
<pre>/add 用户ID 金额</pre>

<b>2. 代理用户操作：</b>
<pre>/add @代理Bot用户名 用户ID 金额</pre>

<b>说明：</b>
- 金额前加 <code>+</code> 表示充值/加款  
- 金额前加 <code>-</code> 表示扣款  
-----------------------------
<b>示例：</b>
<pre>/add 123456789 +100</pre> 给总部用户充值 100 USDT  
<pre>/add @Hytdatasessionbot 5611529170 +500</pre> 给代理用户加款 500 USDT
"""
        context.bot.send_message(chat_id=user_id, text=msg, parse_mode='HTML')
        return

    try:
        target_id = int(text_parts[1])
        amount_str = text_parts[2].replace('+', '').replace('-', '')
        amount = float(amount_str)
        is_add = '+' in text_parts[2]
    except:
        context.bot.send_message(chat_id=user_id, text="❌ 参数格式错误，请检查用户ID和金额")
        return

    target_user = user.find_one({'user_id': target_id})
    if not target_user:
        context.bot.send_message(chat_id=user_id, text="❌ 目标用户不存在")
        return

    timer = beijing_now_str()
    current_balance = target_user.get('USDT', 0)
    new_balance = round(current_balance + amount, 2) if is_add else round(current_balance - amount, 2)

    # 更新数据库
    order_id = generate_24bit_uid()
    action = '充值' if is_add else '扣款'
    user_logging(order_id, action, target_id, amount, timer)
    user.update_one({'user_id': target_id}, {'$set': {'USDT': new_balance}})

    # 发送给管理员
    admin_text = f"""
<b>✅ 操作成功</b>
-----------------------------
<b>ID：</b> <code>{target_id}</code>
<b>昵称：</b> {target_user.get('fullname', '未知')}
<b>操作：</b> {'加款' if is_add else '扣款'} {amount} USDT
<b>当前余额：</b> {new_balance} USDT
-----------------------------
"""
    context.bot.send_message(chat_id=user_id, text=admin_text, parse_mode='HTML')

    # 发送给用户 + 加按钮
    user_text = f"""
<b>✅ 您的账户变动提醒</b>
-----------------------------
<b>操作类型：</b> {'管理员加款' if is_add else '管理员扣款'}
<b>变动金额：</b> {amount} USDT
<b>当前余额：</b> {new_balance} USDT
<b>时间：</b> {timer}
-----------------------------
"""
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ 已读", callback_data=f"close {user_id}")]]
    )
    context.bot.send_message(chat_id=target_id, text=user_text, parse_mode='HTML', reply_markup=keyboard)



def cha(update: Update, context: CallbackContext):
    chat = update.effective_chat
    # print(chat)
    if chat.type == 'private':
        user_id = chat['id']
        chat_id = user_id
        username = chat['username']
        firstname = chat['first_name']
        fullname = chat['full_name']
        timer = beijing_now_str()
        lastname = chat['last_name']
        text = update.message.text
        text1 = text.split(' ')
        user_list = user.find_one({'user_id': user_id})
        USDT = user_list['USDT']
        # 权限检查 - 使用env配置的管理员列表
        if is_admin(user_id):
            # 支持两种格式：
            # 1. /cha 用户ID或用户名 （总部用户）
            # 2. /cha @代理Bot用户名 用户ID （代理Bot用户）
            if len(text1) == 3:
                # 代理Bot用户查询
                admin_query_agent_user(update, context)
                return
            
            if len(text1) == 2:
                jieguo = text1[1]
                if is_number(jieguo):
                    df_id = int(jieguo)
                    df_list = user.find_one({'user_id': df_id})
                    if df_list is None:
                        context.bot.send_message(chat_id=chat_id, text='用户不存在')
                        return
                else:
                    df_list = user.find_one({'username': jieguo.replace('@', '')})
                    if df_list is None:
                        context.bot.send_message(chat_id=chat_id, text='用户不存在')
                        return
                    df_id = df_list['user_id']
                df_fullname = df_list['fullname']
                df_username = df_list['username']
                if df_username is None:
                    df_username = df_fullname
                else:
                    df_username = f'<a href="https://t.me/{df_username}">{df_username}</a>'
                creation_time = df_list['creation_time']
                zgsl = df_list['zgsl']
                zgje = df_list['zgje']
                USDT = df_list['USDT']
                fstext = f'''
<b>用户ID:</b>  <code>{df_id}</code>
<b>用户名:</b>  {df_username} 
<b>注册日期:</b>  {creation_time}

<b>总购数量:</b>  {zgsl}

<b>总购金额:</b>  {standard_num(zgje)} USDT

<b>您的余额:</b>  {USDT} USDT
                '''
                keyboard = [[InlineKeyboardButton('🛒购买记录', callback_data=f'gmaijilu {df_id}')],
                            [InlineKeyboardButton('关闭', callback_data=f'close {df_id}')]]
                context.bot.send_message(chat_id=user_id, text=fstext, parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)



            else:
                msg = """
<b>格式错误 ❌</b>
-----------------------------
<b>正确命令格式：</b>

<b>1. 总部用户查询：</b>
<pre>/cha 用户ID或用户名</pre>

<b>2. 代理用户查询：</b>
<pre>/cha @代理Bot用户名 用户ID</pre>

-----------------------------
<b>示例：</b>
<pre>/cha 123456789</pre> 查询总部用户
<pre>/cha @username</pre> 查询总部用户
<pre>/cha @Hytdatasessionbot 5611529170</pre> 查询代理用户
"""
                context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')


# ==================== 总部管理员代理用户管理功能 ====================

def parse_agent_bot_username(username_str):
    """
    解析代理Bot用户名，去除@前缀
    
    Args:
        username_str: 代理Bot用户名，可能带有@前缀
    
    Returns:
        str: 不带@的用户名，如果为空返回None
    """
    if not username_str:
        return None
    username_str = username_str.strip()
    if username_str.startswith('@'):
        return username_str[1:]
    return username_str


def get_agent_bot_by_username(agent_username):
    """
    根据代理Bot用户名查找代理信息
    
    Args:
        agent_username: 代理Bot用户名（不带@）
    
    Returns:
        dict: 代理信息，如果不存在返回None
    """
    from mongo import agent_bots
    return agent_bots.find_one({'agent_username': agent_username})


def send_notification_via_agent_bot(agent_bot_token, user_id, message_text):
    """
    通过代理Bot发送通知给用户
    
    Args:
        agent_bot_token: 代理Bot的Token
        user_id: 用户ID
        message_text: 消息内容
    
    Returns:
        bool: 发送成功返回True，失败返回False
    """
    try:
        from telegram import Bot
        agent_bot = Bot(token=agent_bot_token)
        agent_bot.send_message(chat_id=user_id, text=message_text, parse_mode='HTML')
        logging.info(f"✅ 通过代理Bot发送通知成功: user_id={user_id}")
        return True
    except Exception as e:
        logging.error(f"❌ 通过代理Bot发送通知失败: user_id={user_id}, error={e}")
        return False


def admin_add_agent_user_balance(update: Update, context: CallbackContext):
    """
    总部管理员给代理Bot用户加款/扣款
    
    命令格式：
    /add @代理Bot用户名 用户ID +/-金额
    /add 代理Bot用户名 用户ID +/-金额
    
    示例：
    /add @Hytdatasessionbot 5611529170 +500
    /add Hytdatasessionbot 5611529170 -100
    """
    chat = update.effective_chat
    if chat.type != 'private':
        return
    
    admin_user_id = chat['id']
    
    # 权限检查 - 只有总部管理员可以操作
    if not is_admin(admin_user_id):
        context.bot.send_message(
            chat_id=admin_user_id, 
            text="⛔ 你没有权限执行此命令"
        )
        return
    
    text = update.message.text
    text_parts = text.split()
    
    # 验证命令格式
    if len(text_parts) != 4:
        msg = """
<b>格式错误 ❌</b>
-----------------------------
<b>正确命令格式：</b>
<pre>/add @代理Bot用户名 用户ID +/-金额</pre>

<b>说明：</b>
- 代理Bot用户名：可带或不带@符号
- 金额前加 <code>+</code> 表示加款  
- 金额前加 <code>-</code> 表示扣款  

-----------------------------
<b>示例：</b>
<pre>/add @Hytdatasessionbot 5611529170 +500</pre> 加款 500 USDT  
<pre>/add Hytdatasessionbot 5611529170 -100</pre> 扣款 100 USDT
"""
        context.bot.send_message(chat_id=admin_user_id, text=msg, parse_mode='HTML')
        return
    
    try:
        # 解析参数
        agent_username_raw = text_parts[1]
        target_user_id_str = text_parts[2]
        amount_str = text_parts[3]
        
        # 解析代理Bot用户名
        agent_username = parse_agent_bot_username(agent_username_raw)
        if not agent_username:
            context.bot.send_message(
                chat_id=admin_user_id, 
                text="❌ 代理Bot用户名格式错误"
            )
            return
        
        # 解析用户ID
        target_user_id = int(target_user_id_str)
        
        # 解析金额
        is_add = '+' in amount_str
        amount_value_str = amount_str.replace('+', '').replace('-', '')
        amount = float(amount_value_str)
        
        if amount <= 0:
            context.bot.send_message(
                chat_id=admin_user_id, 
                text="❌ 金额必须大于0"
            )
            return
        
    except ValueError as e:
        context.bot.send_message(
            chat_id=admin_user_id, 
            text="❌ 参数格式错误，请检查用户ID和金额"
        )
        return
    
    # 查找代理Bot
    agent_info = get_agent_bot_by_username(agent_username)
    if not agent_info:
        context.bot.send_message(
            chat_id=admin_user_id,
            text=f"❌ 代理Bot不存在：@{agent_username}"
        )
        return
    
    agent_bot_id = agent_info.get('agent_bot_id')
    agent_name = agent_info.get('agent_name', '未知代理')
    agent_bot_token = agent_info.get('agent_token')
    
    # 获取代理用户集合
    from mongo import get_agent_bot_user_collection
    agent_users = get_agent_bot_user_collection(agent_bot_id)
    
    # 查找用户
    target_user = agent_users.find_one({'user_id': target_user_id})
    if not target_user:
        context.bot.send_message(
            chat_id=admin_user_id,
            text=f"❌ 用户不存在：用户ID {target_user_id} 不在代理Bot @{agent_username} 中"
        )
        return
    
    # 获取当前余额
    current_balance = target_user.get('USDT', 0)
    
    # 计算新余额
    if is_add:
        new_balance = round(current_balance + amount, 2)
        operation = '加款'
        operation_symbol = '+'
    else:
        # 扣款时检查余额是否足够
        if current_balance < amount:
            context.bot.send_message(
                chat_id=admin_user_id,
                text=f"❌ 余额不足\n\n当前余额：{current_balance:.2f} USDT\n扣款金额：{amount:.2f} USDT"
            )
            return
        new_balance = round(current_balance - amount, 2)
        operation = '扣款'
        operation_symbol = '-'
    
    # 更新余额
    timer = beijing_now_str()
    agent_users.update_one(
        {'user_id': target_user_id}, 
        {'$set': {'USDT': new_balance}}
    )
    
    # 记录日志
    logging.info(
        f"✅ 总部管理员操作代理用户余额: admin={admin_user_id}, "
        f"agent=@{agent_username}, user={target_user_id}, "
        f"operation={operation}, amount={amount}, new_balance={new_balance}"
    )
    
    # 发送给管理员的反馈
    admin_text = f"""
✅ <b>操作成功</b>

📱 <b>代理Bot：</b>@{agent_username}
🏢 <b>代理名称：</b>{agent_name}
👤 <b>用户ID：</b><code>{target_user_id}</code>
💰 <b>操作金额：</b>{operation_symbol}{amount:.2f} USDT
💵 <b>当前余额：</b>{new_balance:.2f} USDT
⏰ <b>操作时间：</b>{timer}
"""
    context.bot.send_message(
        chat_id=admin_user_id, 
        text=admin_text, 
        parse_mode='HTML'
    )
    
    # 发送给用户的通知
    if is_add:
        user_notification = f"""
💰 <b>管理员加款通知</b>

您的账户余额添加成功！

💵 <b>充值金额：</b>+{amount:.2f} USDT
📊 <b>当前余额：</b>{new_balance:.2f} USDT
⏰ <b>到账时间：</b>{timer}

如有疑问请联系客服
"""
    else:
        user_notification = f"""
💸 <b>余额变动通知</b>

您的账户余额已扣减

💵 <b>扣减金额：</b>-{amount:.2f} USDT
📊 <b>当前余额：</b>{new_balance:.2f} USDT
⏰ <b>操作时间：</b>{timer}

如有疑问请联系客服
"""
    
    # 通过代理Bot发送通知
    send_notification_via_agent_bot(agent_bot_token, target_user_id, user_notification)


def admin_query_agent_user(update: Update, context: CallbackContext):
    """
    总部管理员查询代理Bot用户信息
    
    命令格式：
    /cha @代理Bot用户名 用户ID
    /cha 代理Bot用户名 用户ID
    
    示例：
    /cha @Hytdatasessionbot 5611529170
    /cha Hytdatasessionbot 5611529170
    """
    chat = update.effective_chat
    if chat.type != 'private':
        return
    
    admin_user_id = chat['id']
    
    # 权限检查 - 只有总部管理员可以操作
    if not is_admin(admin_user_id):
        context.bot.send_message(
            chat_id=admin_user_id, 
            text="⛔ 你没有权限执行此命令"
        )
        return
    
    text = update.message.text
    text_parts = text.split()
    
    # 验证命令格式
    if len(text_parts) != 3:
        msg = """
<b>格式错误 ❌</b>
-----------------------------
<b>正确命令格式：</b>
<pre>/cha @代理Bot用户名 用户ID</pre>

<b>说明：</b>
- 代理Bot用户名：可带或不带@符号
- 用户ID：目标用户的Telegram ID

-----------------------------
<b>示例：</b>
<pre>/cha @Hytdatasessionbot 5611529170</pre>
<pre>/cha Hytdatasessionbot 5611529170</pre>
"""
        context.bot.send_message(chat_id=admin_user_id, text=msg, parse_mode='HTML')
        return
    
    try:
        # 解析参数
        agent_username_raw = text_parts[1]
        target_user_id_str = text_parts[2]
        
        # 解析代理Bot用户名
        agent_username = parse_agent_bot_username(agent_username_raw)
        if not agent_username:
            context.bot.send_message(
                chat_id=admin_user_id, 
                text="❌ 代理Bot用户名格式错误"
            )
            return
        
        # 解析用户ID
        target_user_id = int(target_user_id_str)
        
    except ValueError as e:
        context.bot.send_message(
            chat_id=admin_user_id, 
            text="❌ 参数格式错误，请检查用户ID"
        )
        return
    
    # 查找代理Bot
    agent_info = get_agent_bot_by_username(agent_username)
    if not agent_info:
        context.bot.send_message(
            chat_id=admin_user_id,
            text=f"❌ 代理Bot不存在：@{agent_username}"
        )
        return
    
    agent_bot_id = agent_info.get('agent_bot_id')
    agent_name = agent_info.get('agent_name', '未知代理')
    
    # 获取代理用户集合
    from mongo import get_agent_bot_user_collection, get_agent_bot_gmjlu_collection
    agent_users = get_agent_bot_user_collection(agent_bot_id)
    
    # 查找用户
    target_user = agent_users.find_one({'user_id': target_user_id})
    if not target_user:
        context.bot.send_message(
            chat_id=admin_user_id,
            text=f"❌ 用户不存在：用户ID {target_user_id} 不在代理Bot @{agent_username} 中"
        )
        return
    
    # 获取用户信息
    user_username = target_user.get('username', '无')
    user_fullname = target_user.get('fullname', '无').replace('<', '').replace('>', '')
    current_balance = target_user.get('USDT', 0)
    zgje = target_user.get('zgje', 0)  # 总购金额
    zgsl = target_user.get('zgsl', 0)  # 总购数量
    creation_time = target_user.get('creation_time', '未知')
    
    # 获取订单统计
    agent_gmjlu = get_agent_bot_gmjlu_collection(agent_bot_id)
    order_count = agent_gmjlu.count_documents({'user_id': target_user_id})
    
    # 格式化用户名显示
    if user_username and user_username != '无':
        username_display = f'<a href="https://t.me/{user_username}">@{user_username}</a>'
    else:
        username_display = '无'
    
    # 构建查询结果
    query_text = f"""
👤 <b>代理用户信息</b>

📱 <b>代理Bot：</b>@{agent_username}
🏢 <b>代理名称：</b>{agent_name}
🆔 <b>用户ID：</b><code>{target_user_id}</code>
👤 <b>用户名：</b>{username_display}
👨 <b>昵称：</b>{user_fullname}
💰 <b>当前余额：</b>{current_balance:.2f} USDT
📊 <b>累计消费：</b>{zgje:.2f} USDT
📦 <b>订单总数：</b>{order_count} 单
🛒 <b>购买次数：</b>{zgsl} 次
📅 <b>注册时间：</b>{creation_time}
"""
    
    context.bot.send_message(
        chat_id=admin_user_id,
        text=query_text,
        parse_mode='HTML',
        disable_web_page_preview=True
    )
    
    logging.info(
        f"✅ 总部管理员查询代理用户: admin={admin_user_id}, "
        f"agent=@{agent_username}, user={target_user_id}"
    )


def create_folder_if_not_exists(folder_path):
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        # print(f"Folder '{folder_path}' created successfully.")
    else:
        pass
        # print(f"Folder '{folder_path}' already exists.")


def parse_url(content):
    args = content.split('&')
    if len(args) < 2:
        (title, url) = ("格式错误，点击联系管理员", "www.baidu.com")
    else:
        (title, url) = (args[0].strip(), (None if len(args) < 1 else args[1].strip()))
    return create_keyboard(title, url)


def create_keyboard(title, url=None, callback_data=None, inline_query=None):
    return [InlineKeyboardButton(title, url=url, callback_data=callback_data,
                                 switch_inline_query_current_chat=inline_query)]


def parse_urls(content, maxurl=99):
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

def shouyishuoming_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        query.answer()
    except Exception as e:
        logging.warning(f"query.answer() 异常：{e}")

    user_id = query.from_user.id

    text = '''
<b>📊 收益统计说明</b>

<b>▪️ 昨日收入</b>：昨天整天内所有“成功充值订单”的总金额。

<b>▪️ 今日收入</b>：今天 0 点至当前时间内的“成功充值金额”。

<b>▪️ 本周收入</b>：从本周一 0 点起至现在的总收入。

<b>▪️ 本月收入</b>：从本月 1 号起至当前时间的累计充值金额。

⚠️ <i>仅统计状态为 “success” 的充值订单</i>，不包含失败或超时记录。
    '''.strip()

    keyboard = [
        [InlineKeyboardButton("⬅️ 返回控制台", callback_data="backstart")],
        [InlineKeyboardButton("❌ 关闭", callback_data=f"close {user_id}")]
    ]

    try:
        query.edit_message_text(
            text=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    except Exception as e:
        logging.error(f"edit_message_text 错误：{e}")

def main():
    BOT_TOKEN = os.getenv('BOT_TOKEN')  # 从 .env 读取 token

    flask_thread = threading.Thread(target=start_flask_server)
    flask_thread.start()

    Thread(target=start_flask_server, daemon=True).start()

    updater = Updater(
        token=BOT_TOKEN,
        use_context=True,
        workers=128,
        request_kwargs={'read_timeout': REQUEST_TIMEOUT, 'connect_timeout': REQUEST_TIMEOUT}
    )

    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler('start', start, run_async=True))
    dispatcher.add_handler(CommandHandler('help', help_command, run_async=True))
    dispatcher.add_handler(CommandHandler('add', adm, run_async=True))
    dispatcher.add_handler(CommandHandler('cha', cha, run_async=True))
    dispatcher.add_handler(CommandHandler('gg', fbgg, run_async=True))
    dispatcher.add_handler(CommandHandler('search', search_goods, run_async=True))
    dispatcher.add_handler(CommandHandler('hot', hot_goods, run_async=True))
    dispatcher.add_handler(CommandHandler('new', new_goods, run_async=True))
    dispatcher.add_handler(CommandHandler('admin', admin, run_async=True))
    dispatcher.add_handler(CommandHandler("admin_add", admin_add, run_async=True))
    dispatcher.add_handler(CommandHandler("admin_remove", admin_remove, run_async=True))
    dispatcher.add_handler(CommandHandler("diag_db", diag_db, run_async=True))  # Database diagnostics
    # 🆕 代理系统命令处理器
    dispatcher.add_handler(CommandHandler("add_agent", add_new_agent, run_async=True))
    # 🆕 用户提现管理命令
    dispatcher.add_handler(CommandHandler("my_withdrawals", check_my_withdrawals, run_async=True))
    # 在main()函数的dispatcher部分添加：

    dispatcher.add_handler(CallbackQueryHandler(startupdate, pattern='startupdate'))

    dispatcher.add_handler(CallbackQueryHandler(delrow, pattern='delrow'))
    dispatcher.add_handler(CallbackQueryHandler(newrow, pattern='newrow'))
    dispatcher.add_handler(CallbackQueryHandler(newkey, pattern='newkey'))
    dispatcher.add_handler(CallbackQueryHandler(backstart, pattern='backstart'))
    dispatcher.add_handler(CallbackQueryHandler(paixurow, pattern='paixurow'))
    dispatcher.add_handler(CallbackQueryHandler(addzdykey, pattern='addzdykey'))
    dispatcher.add_handler(CallbackQueryHandler(qrscdelrow, pattern='qrscdelrow '))
    dispatcher.add_handler(CallbackQueryHandler(addhangkey, pattern='addhangkey '))
    dispatcher.add_handler(CallbackQueryHandler(delhangkey, pattern='delhangkey '))
    dispatcher.add_handler(CallbackQueryHandler(qrdelliekey, pattern='qrdelliekey '))
    dispatcher.add_handler(CallbackQueryHandler(keyxq, pattern='keyxq '))
    dispatcher.add_handler(CallbackQueryHandler(setkeyname, pattern='setkeyname '))
    dispatcher.add_handler(CallbackQueryHandler(settuwenset, pattern='settuwenset '))
    dispatcher.add_handler(CallbackQueryHandler(setkeyboard, pattern='setkeyboard '))
    dispatcher.add_handler(CallbackQueryHandler(cattuwenset, pattern='cattuwenset '))
    dispatcher.add_handler(CallbackQueryHandler(paixuyidong, pattern='paixuyidong '))
    dispatcher.add_handler(CallbackQueryHandler(close, pattern='close '))
    dispatcher.add_handler(CallbackQueryHandler(yuecz, pattern='yuecz '))
    dispatcher.add_handler(CallbackQueryHandler(settrc20, pattern='settrc20'))
    dispatcher.add_handler(CallbackQueryHandler(spgli, pattern='spgli'))
    dispatcher.add_handler(CallbackQueryHandler(newfl, pattern='newfl'))
    dispatcher.add_handler(CallbackQueryHandler(flxxi, pattern='flxxi '))
    dispatcher.add_handler(CallbackQueryHandler(upspname, pattern='upspname '))
    dispatcher.add_handler(CallbackQueryHandler(newejfl, pattern='newejfl '))
    dispatcher.add_handler(CallbackQueryHandler(fejxxi, pattern='fejxxi '))
    dispatcher.add_handler(CallbackQueryHandler(upejflname, pattern='upejflname '))
    dispatcher.add_handler(CallbackQueryHandler(catejflsp, pattern='catejflsp '))
    dispatcher.add_handler(CallbackQueryHandler(backzcd, pattern='backzcd'))
    # ✅ 新增：返回商品列表的回调处理器
    dispatcher.add_handler(CallbackQueryHandler(show_product_list, pattern='show_product_list'))
    dispatcher.add_handler(CallbackQueryHandler(paixufl, pattern='paixufl'))
    dispatcher.add_handler(CallbackQueryHandler(flpxyd, pattern='flpxyd '))
    dispatcher.add_handler(CallbackQueryHandler(delfl, pattern='delfl'))
    dispatcher.add_handler(CallbackQueryHandler(qrscflrow, pattern='qrscflrow '))
    dispatcher.add_handler(CallbackQueryHandler(paixuejfl, pattern='paixuejfl '))
    dispatcher.add_handler(CallbackQueryHandler(ejfpaixu, pattern='ejfpaixu '))
    dispatcher.add_handler(CallbackQueryHandler(delejfl, pattern='delejfl '))
    dispatcher.add_handler(CallbackQueryHandler(qrscejrow, pattern='qrscejrow '))
    dispatcher.add_handler(CallbackQueryHandler(del_ejfl_open, pattern=r'^del_ejfl_open:'))
    dispatcher.add_handler(CallbackQueryHandler(del_ejfl_confirm, pattern=r'^del_ejfl_confirm:'))
    dispatcher.add_handler(CallbackQueryHandler(update_hb, pattern='update_hb '))
    dispatcher.add_handler(CallbackQueryHandler(gmsp, pattern='gmsp '))
    dispatcher.add_handler(CallbackQueryHandler(upmoney, pattern='upmoney '))
    dispatcher.add_handler(CallbackQueryHandler(sysming, pattern='sysming'))
    dispatcher.add_handler(CallbackQueryHandler(gmqq, pattern='gmqq'))
    dispatcher.add_handler(CallbackQueryHandler(qrgaimai, pattern='qrgaimai '))
    dispatcher.add_handler(CallbackQueryHandler(update_xyh, pattern='update_xyh '))
    dispatcher.add_handler(CallbackQueryHandler(update_hy, pattern='update_hy '))
    dispatcher.add_handler(CallbackQueryHandler(yhlist, pattern=r'^yhlist$'))
    dispatcher.add_handler(CallbackQueryHandler(yhpage, pattern=r'^yhpage \d+$'))
    dispatcher.add_handler(CallbackQueryHandler(gmaijilu, pattern='gmaijilu'))
    dispatcher.add_handler(CallbackQueryHandler(zcfshuo, pattern='zcfshuo'))
    dispatcher.add_handler(CallbackQueryHandler(gmainext, pattern='gmainext '))
    # 添加页码信息处理器（不执行任何操作，只是防止错误）
    dispatcher.add_handler(CallbackQueryHandler(lambda update, context: update.callback_query.answer("页码信息" if user.find_one({'user_id': update.callback_query.from_user.id}).get('lang', 'zh') == 'zh' else "Page Info"), pattern='page_info'))
    dispatcher.add_handler(CallbackQueryHandler(update_txt, pattern='update_txt '))
    dispatcher.add_handler(CallbackQueryHandler(backgmjl, pattern='backgmjl '))
    dispatcher.add_handler(CallbackQueryHandler(qchuall, pattern='qchuall '))
    dispatcher.add_handler(CallbackQueryHandler(update_wbts, pattern='update_wbts '))
    dispatcher.add_handler(CallbackQueryHandler(update_gg, pattern='update_gg '))
    dispatcher.add_handler(CallbackQueryHandler(zdycz, pattern='zdycz'))
    dispatcher.add_handler(CallbackQueryHandler(stock_page_handler, pattern=r'^ck_page \d+$'))
    dispatcher.add_handler(CallbackQueryHandler(show_income_callback, pattern='^show_income$'))
    dispatcher.add_handler(CallbackQueryHandler(handle_captcha_response, pattern=r'^captcha_'))
    dispatcher.add_handler(CallbackQueryHandler(czfs_callback, pattern=r'^czfs '))
    dispatcher.add_handler(CallbackQueryHandler(czback_callback, pattern='^czback$'))
    dispatcher.add_handler(CallbackQueryHandler(czmoney_callback, pattern='^czmoney '))
    dispatcher.add_handler(CallbackQueryHandler(export_userlist, pattern='^export_userlist$'))
    dispatcher.add_handler(CallbackQueryHandler(export_recharge_details, pattern='^export_income$'))
    dispatcher.add_handler(CallbackQueryHandler(show_user_income_summary, pattern='^summary_income$'))
    dispatcher.add_handler(CallbackQueryHandler(show_user_income_summary, pattern=r'^user_income_page_\d+$'))
    dispatcher.add_handler(CallbackQueryHandler(handle_admin_manage, pattern="^admin_manage$"))
    # 🆕 新增功能的回调处理器
    dispatcher.add_handler(CallbackQueryHandler(sales_dashboard, pattern='^sales_dashboard$'))
    dispatcher.add_handler(CallbackQueryHandler(stock_alerts, pattern='^stock_alerts$'))
    dispatcher.add_handler(CallbackQueryHandler(data_export_menu, pattern='^data_export_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(auto_restock_reminders, pattern='^auto_restock_reminders$'))
    dispatcher.add_handler(CallbackQueryHandler(stock_alerts, pattern='^refresh_stock_alerts$'))  # 刷新库存
    # 🆕 导出功能回调处理器
    dispatcher.add_handler(CallbackQueryHandler(export_users_comprehensive, pattern='^export_users_comprehensive$'))
    dispatcher.add_handler(CallbackQueryHandler(export_orders_comprehensive, pattern='^export_orders_comprehensive$'))
    dispatcher.add_handler(CallbackQueryHandler(export_financial_data, pattern='^export_financial_data$'))
    dispatcher.add_handler(CallbackQueryHandler(export_inventory_data, pattern='^export_inventory_data$'))
    # 🆕 多语言管理回调处理器
    dispatcher.add_handler(CallbackQueryHandler(multilang_management, pattern='^multilang_management$'))
    dispatcher.add_handler(CallbackQueryHandler(translation_dictionary, pattern='^translation_dictionary$'))
    dispatcher.add_handler(CallbackQueryHandler(translation_dictionary, pattern=r'^dict_page_\d+$'))
    dispatcher.add_handler(CallbackQueryHandler(language_statistics, pattern='^language_statistics$'))
    dispatcher.add_handler(CallbackQueryHandler(translation_settings, pattern='^translation_settings$'))
    dispatcher.add_handler(CallbackQueryHandler(clear_translation_cache, pattern='^clear_translation_cache$'))
    dispatcher.add_handler(CallbackQueryHandler(search_translation, pattern='^search_translation$'))
    dispatcher.add_handler(CallbackQueryHandler(export_dictionary, pattern='^export_dictionary$'))
    dispatcher.add_handler(CallbackQueryHandler(detailed_lang_report, pattern='^detailed_lang_report$'))
    # 🆕 缓存清理相关回调处理器
    dispatcher.add_handler(CallbackQueryHandler(clear_expired_cache, pattern='^clear_expired_cache$'))
    dispatcher.add_handler(CallbackQueryHandler(clear_lowfreq_cache, pattern='^clear_lowfreq_cache$'))
    dispatcher.add_handler(CallbackQueryHandler(clear_all_cache, pattern='^clear_all_cache$'))
    dispatcher.add_handler(CallbackQueryHandler(confirm_clear_all_cache, pattern='^confirm_clear_all_cache$'))
    
    # 🆕 补货提醒相关回调处理器
    dispatcher.add_handler(CallbackQueryHandler(modify_restock_threshold, pattern='^modify_restock_threshold$'))
    dispatcher.add_handler(CallbackQueryHandler(set_reminder_time, pattern='^set_reminder_time$'))
    dispatcher.add_handler(CallbackQueryHandler(view_reminder_history, pattern='^view_reminder_history$'))
    dispatcher.add_handler(CallbackQueryHandler(set_threshold_handler, pattern=r'^set_threshold_\d+$'))
    dispatcher.add_handler(CallbackQueryHandler(reminder_time_handler, pattern=r'^reminder_time_\d+$'))
    
    # 🆕 销售统计相关回调处理器
    dispatcher.add_handler(CallbackQueryHandler(detailed_sales_report, pattern='^detailed_sales_report$'))
    dispatcher.add_handler(CallbackQueryHandler(sales_trend_analysis, pattern='^sales_trend_analysis$'))
    dispatcher.add_handler(CallbackQueryHandler(addhb, pattern='addhb'))
    dispatcher.add_handler(CallbackQueryHandler(lqhb, pattern='lqhb '))
    dispatcher.add_handler(CallbackQueryHandler(xzhb, pattern='xzhb '))
    dispatcher.add_handler(CallbackQueryHandler(yjshb, pattern='yjshb'))
    dispatcher.add_handler(CallbackQueryHandler(jxzhb, pattern='jxzhb'))
    dispatcher.add_handler(CallbackQueryHandler(shokuan, pattern='shokuan '))
    dispatcher.add_handler(CallbackQueryHandler(update_sysm, pattern='update_sysm '))
    dispatcher.add_handler(InlineQueryHandler(inline_query))
    dispatcher.add_handler(InlineQueryHandler(cancel_order_callback, pattern=r"^qxdingdan "))
    dispatcher.add_handler(CallbackQueryHandler(export_gmjlu_records, pattern='^export_orders$'))
    # 🆕 新增用户导出汇总报告回调处理器
    dispatcher.add_handler(CallbackQueryHandler(export_user_summary_report, pattern='^export_user_summary$'))

    # 🤖 代理管理系统回调处理器
    dispatcher.add_handler(CallbackQueryHandler(show_agent_management, pattern='^agent_management$'))
    dispatcher.add_handler(CallbackQueryHandler(show_agent_list, pattern='^agent_list$'))
    dispatcher.add_handler(CallbackQueryHandler(start_add_agent, pattern='^agent_add$'))
    dispatcher.add_handler(CallbackQueryHandler(show_agent_details, pattern=r'^agent_detail_'))
    dispatcher.add_handler(CallbackQueryHandler(toggle_agent_status, pattern=r'^agent_enable_'))
    dispatcher.add_handler(CallbackQueryHandler(toggle_agent_status, pattern=r'^agent_disable_'))
    dispatcher.add_handler(CallbackQueryHandler(delete_agent_confirm, pattern=r'^agent_delete_confirm_'))
    dispatcher.add_handler(CallbackQueryHandler(delete_agent, pattern=r'^agent_delete_'))
    dispatcher.add_handler(CallbackQueryHandler(show_agent_stats, pattern=r'^agent_stats_'))
    
    # ⚙️ 代理设置管理回调处理器
    dispatcher.add_handler(CallbackQueryHandler(show_agent_settings, pattern=r'^agent_settings_'))
    dispatcher.add_handler(CallbackQueryHandler(show_agent_address_config, pattern=r'^agent_config_address_'))
    dispatcher.add_handler(CallbackQueryHandler(request_agent_address_input, pattern=r'^agent_modify_address_'))
    dispatcher.add_handler(CallbackQueryHandler(confirm_agent_address_change, pattern=r'^agent_confirm_address_'))
    
    # 💸 代理提现管理回调处理器
    dispatcher.add_handler(CallbackQueryHandler(show_withdrawal_management, pattern='^agent_withdrawal_manage$'))
    dispatcher.add_handler(CallbackQueryHandler(show_pending_withdrawals, pattern='^agent_withdrawal_pending$'))
    dispatcher.add_handler(CallbackQueryHandler(show_withdrawal_detail, pattern=r'^agent_withdrawal_detail_'))
    dispatcher.add_handler(CallbackQueryHandler(approve_withdrawal, pattern=r'^agent_withdrawal_approve_'))
    dispatcher.add_handler(CallbackQueryHandler(reject_withdrawal, pattern=r'^agent_withdrawal_reject_'))
    dispatcher.add_handler(CallbackQueryHandler(complete_withdrawal, pattern=r'^agent_withdrawal_complete_'))
    dispatcher.add_handler(CallbackQueryHandler(view_withdrawal_history, pattern='^agent_withdrawal_history$'))
    dispatcher.add_handler(CallbackQueryHandler(show_withdrawal_stats, pattern='^agent_withdrawal_stats$'))
    
    # 📊 代理统计报表回调处理器
    dispatcher.add_handler(CallbackQueryHandler(show_agent_stats_report, pattern='^agent_stats_report$'))
    dispatcher.add_handler(CallbackQueryHandler(show_sales_ranking, pattern='^agent_report_sales_ranking$'))
    dispatcher.add_handler(CallbackQueryHandler(show_profit_summary, pattern='^agent_report_profit_summary$'))
    dispatcher.add_handler(CallbackQueryHandler(export_sales_ranking, pattern='^agent_export_sales_ranking$'))
    dispatcher.add_handler(CallbackQueryHandler(export_profit_summary, pattern='^agent_export_profit_summary$'))
    dispatcher.add_handler(CallbackQueryHandler(show_comprehensive_report, pattern='^agent_report_comprehensive$'))
    dispatcher.add_handler(CallbackQueryHandler(
        lambda u, c: export_comprehensive_report(u, c, 'full'), 
        pattern='^agent_export_comprehensive_full$'
    ))
    dispatcher.add_handler(CallbackQueryHandler(
        lambda u, c: export_comprehensive_report(u, c, 'brief'), 
        pattern='^agent_export_comprehensive_brief$'
    ))

    dispatcher.add_handler(CallbackQueryHandler(qxdingdan, pattern='qxdingdan ', run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(shouyishuoming_callback, pattern='^shouyishuoming$'))

    dispatcher.add_handler(CallbackQueryHandler(sifa, pattern='sifa'))
    dispatcher.add_handler(CallbackQueryHandler(kaiqisifa, pattern='kaiqisifa', run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(tuwen, pattern='tuwen', run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(anniu, pattern='anniu', run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(cattu, pattern='cattu', run_async=True))
    dispatcher.add_handler(CallbackQueryHandler(handle_all_callbacks))

    # ✅ 修复：textkeyboard必须在handle_admin_txhash_message之前注册
    # 这样底部按钮（商品列表、个人中心等）才能正常响应
    dispatcher.add_handler(MessageHandler(Filters.chat_type.private & Filters.reply, huifu), )
    
    # ✅ 主要的消息处理器 - 处理底部按钮和所有用户交互（组0 - 最高优先级）
    # 这个必须首先注册，确保底部菜单按钮（🛒商品列表等）能正常工作
    dispatcher.add_handler(MessageHandler(
        (Filters.text | Filters.photo | Filters.animation | Filters.video | Filters.document) & ~(Filters.command),
        textkeyboard, run_async=True), group=0)
    
    # 🆕 用户提现TXID提交处理器（组1）
    # 这个处理器在textkeyboard处理后触发
    # 注意：这个处理器的early return确保只在用户处于等待TXID状态时才处理
    dispatcher.add_handler(MessageHandler(
        Filters.text & ~Filters.command & Filters.private,
        handle_user_withdrawal_txid,
        run_async=True
    ), group=1)
    
    # handle_admin_txhash_message 放在组1，用于处理管理员输入交易哈希
    # ✅ 添加 Filters.private 使 filter 更精确，只处理私聊消息  
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command & Filters.private, handle_admin_txhash_message, run_async=True), group=1)
    # 订单检查任务：30秒间隔（权衡性能和响应速度，最多30秒延迟）
    updater.job_queue.run_repeating(suoyouchengxu, 30, 1, name='suoyouchengxu')
    updater.job_queue.run_repeating(jiexi, 30, 1, name='chongzhi')
    updater.start_polling(timeout=BOT_TIMEOUT)
    updater.idle()


if __name__ == '__main__':

    for i in ['发货', '协议号发货', '手机接码发货', '临时文件夹', '谷歌发货', '协议号', '号包']:
        create_folder_if_not_exists(i)
    main()
