"""
代理支付系统核心文件 - USDT TRC20 独立支付系统
实现用户自助充值功能，包含订单管理、区块链监控、安全验证等功能
"""

import os
import sys
import time
import random
import logging
import threading
import itertools
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from decimal import Decimal

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

try:
    from tronpy.providers import HTTPProvider
    from tronpy import Tron
except ImportError:
    logging.warning("⚠️ tronpy 未安装，支付系统将无法正常工作")
    Tron = None
    HTTPProvider = None

# 加载环境变量
from pathlib import Path
load_dotenv(Path(__file__).parent / '.env')

# 日志配置
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/agent_payment.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)


# ================================ 配置类 ================================

class SecurityConfig:
    """安全配置"""
    # USDT TRC20 官方合约地址
    OFFICIAL_USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    
    # 最小充值金额（防0元购）
    MIN_DEPOSIT_AMOUNT = 0.01
    
    # 订单超时时间（秒）
    ORDER_TIMEOUT = 600  # 10分钟
    
    # 区块链记录时效限制（秒）
    BLOCKCHAIN_TIME_LIMIT = 900  # 15分钟
    
    # 小数点位数（防撞单）
    DECIMAL_PLACES = 4
    
    # 金额匹配容差
    AMOUNT_TOLERANCE = 0.0001
    
    # USDT精度（TRC20）
    USDT_DECIMALS = 1_000_000


class Config:
    """基础配置"""
    # 充值地址（由总部统一配置）
    DEPOSIT_ADDRESS = os.getenv('AGENT_DEPOSIT_ADDRESS', '')
    
    # 代理Bot Token
    BOT_TOKEN = os.getenv('AGENT_BOT_TOKEN', '')
    
    # Tron API Keys（逗号分隔，支持轮换）
    TRON_API_KEYS = os.getenv('TRON_API_KEYS', '').split(',')
    
    # 轮询间隔（秒）
    POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '3'))
    
    # 订单清理间隔（秒）
    ORDER_CLEANUP_INTERVAL = int(os.getenv('ORDER_CLEANUP_INTERVAL', '30'))
    
    # MongoDB配置
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/')
    MONGO_DB = os.getenv('MONGO_DB_BOT', '9hao1bot')
    
    # 代理Bot ID
    AGENT_BOT_ID = os.getenv('AGENT_BOT_ID', '')
    
    # 充值金额限制
    MIN_RECHARGE_AMOUNT = float(os.getenv('MIN_RECHARGE_AMOUNT', '1'))
    MAX_RECHARGE_AMOUNT = float(os.getenv('MAX_RECHARGE_AMOUNT', '10000'))
    
    @classmethod
    def validate(cls):
        """验证配置"""
        if not cls.DEPOSIT_ADDRESS:
            raise ValueError("❌ AGENT_DEPOSIT_ADDRESS 未配置")
        if not cls.BOT_TOKEN:
            raise ValueError("❌ AGENT_BOT_TOKEN 未配置")
        if not cls.TRON_API_KEYS or cls.TRON_API_KEYS == ['']:
            raise ValueError("❌ TRON_API_KEYS 未配置")
        if not cls.AGENT_BOT_ID:
            raise ValueError("❌ AGENT_BOT_ID 未配置")
        logging.info("✅ 支付系统配置验证通过")


# ================================ 数据库管理 ================================

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self):
        self.client = MongoClient(Config.MONGO_URI)
        self.db = self.client[Config.MONGO_DB]
        
        # 获取代理专属集合名称后缀
        agent_id_suffix = Config.AGENT_BOT_ID.replace('agent_', '') if Config.AGENT_BOT_ID.startswith('agent_') else Config.AGENT_BOT_ID
        
        # 集合
        self.topup = self.db[f'agent_topup_{agent_id_suffix}']  # 充值订单
        self.users = self.db[f'agent_users_{agent_id_suffix}']  # 用户信息
        self.processed_transactions = self.db['processed_transactions']  # 已处理交易
        self.blacklist_addresses = self.db['blacklist_addresses']  # 黑名单地址
        
        # 创建索引
        self._create_indexes()
        logging.info("✅ 数据库管理器初始化完成")
    
    def _create_indexes(self):
        """创建索引"""
        try:
            # 充值订单索引
            self.topup.create_index('order_id', unique=True)
            self.topup.create_index('user_id')
            self.topup.create_index('status')
            self.topup.create_index('exact_amount')
            self.topup.create_index('created_at')
            
            # 已处理交易索引
            self.processed_transactions.create_index('tx_id', unique=True)
            
            # 黑名单地址索引
            self.blacklist_addresses.create_index('address', unique=True)
            
            logging.info("✅ 数据库索引创建完成")
        except Exception as e:
            logging.error(f"❌ 创建数据库索引失败: {e}")
    
    def create_order(self, user_id: int, amount: float, exact_amount: float, message_id: int) -> str:
        """创建充值订单"""
        order_id = self._generate_order_id()
        order = {
            'order_id': order_id,
            'user_id': user_id,
            'amount': amount,  # 用户输入的金额
            'exact_amount': exact_amount,  # 精确金额（带4位小数）
            'message_id': message_id,  # 订单消息ID（用于更新/删除）
            'status': 'pending',  # pending/completed/cancelled/expired
            'created_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(seconds=SecurityConfig.ORDER_TIMEOUT)
        }
        self.topup.insert_one(order)
        logging.info(f"✅ 创建充值订单: order_id={order_id}, user_id={user_id}, amount={exact_amount}")
        return order_id
    
    def get_order(self, order_id: str) -> Optional[Dict]:
        """获取订单"""
        return self.topup.find_one({'order_id': order_id})
    
    def get_pending_orders(self) -> List[Dict]:
        """获取所有待处理订单"""
        return list(self.topup.find({'status': 'pending'}))
    
    def update_order_status(self, order_id: str, status: str):
        """更新订单状态"""
        self.topup.update_one(
            {'order_id': order_id},
            {'$set': {'status': status, 'updated_at': datetime.now()}}
        )
        logging.info(f"✅ 更新订单状态: order_id={order_id}, status={status}")
    
    def is_transaction_processed(self, tx_id: str) -> bool:
        """检查交易是否已处理"""
        return self.processed_transactions.find_one({'tx_id': tx_id}) is not None
    
    def mark_transaction_processed(self, tx_id: str, order_id: str, amount: float):
        """标记交易已处理"""
        self.processed_transactions.insert_one({
            'tx_id': tx_id,
            'order_id': order_id,
            'amount': amount,
            'processed_at': datetime.now()
        })
        logging.info(f"✅ 标记交易已处理: tx_id={tx_id}, order_id={order_id}")
    
    def is_address_blacklisted(self, address: str) -> bool:
        """检查地址是否在黑名单"""
        return self.blacklist_addresses.find_one({'address': address}) is not None
    
    def update_user_balance(self, user_id: int, amount: float) -> bool:
        """更新用户余额"""
        result = self.users.update_one(
            {'user_id': user_id},
            {'$inc': {'USDT': amount}}
        )
        if result.modified_count > 0:
            logging.info(f"✅ 更新用户余额: user_id={user_id}, amount=+{amount}")
            return True
        return False
        
    def get_user_balance(self, user_id: int) -> float:
        """获取用户余额"""
        user = self.users.find_one({'user_id': user_id})
        return user.get('USDT', 0) if user else 0
        
    def _generate_order_id(self) -> str:
        """生成订单ID"""
        import uuid
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        # 使用UUID4增加随机性，避免可预测性和并发冲突
        random_suffix = str(uuid.uuid4()).replace('-', '')[:8].upper()
        return f"CZ{timestamp}{random_suffix}"


# ================================ Bot消息管理 ================================

class BotManager:
    """Bot消息管理器"""
    
    def __init__(self):
        self.bot = Bot(token=Config.BOT_TOKEN)
        logging.info("✅ Bot管理器初始化完成")
    
    def send_order_message(self, user_id: int, order_id: str, exact_amount: float) -> Optional[int]:
        """发送订单消息"""
        text = f"""💳 <b>USDT Recharge</b>

📍 <b>Deposit Address:</b>
<code>{Config.DEPOSIT_ADDRESS}</code>

💰 <b>Please transfer exact amount:</b>
<code>{exact_amount:.4f} USDT</code>

⏰ <b>Valid for: </b> 10 minutes
📋 <b>Order ID:</b><code>{order_id}</code>

⚠️ <b>Please transfer the exact amount, otherwise it cannot be credited automatically!</b>"""
        
        keyboard = [
            [InlineKeyboardButton("❌ Cancel Order", callback_data=f"cancel_order_{order_id}")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        
        try:
            message = self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return message.message_id
        except Exception as e: 
            logging.error(f"❌ 发送订单消息失败: {e}")
            return None
    def update_order_message(self, user_id: int, message_id: int, status: str):
        """更新订单消息状态"""
        status_text = {
            'completed': '✅ Recharge successful! Balance credited',
            'cancelled':  '❌ Order cancelled',
            'expired': '⏰ Order expired'
        }
        
        try: 
            self.bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=status_text.get(status, 'Order status updated'),
                parse_mode='HTML'
            )
        except Exception as e:
            logging.error(f"❌ 更新订单消息失败: {e}")
    
    def delete_order_message(self, user_id: int, message_id:  int):
        """删除订单消息"""
        try:
            self.bot.delete_message(chat_id=user_id, message_id=message_id)
        except Exception as e: 
            logging.error(f"❌ 删除订单消息失败:  {e}")
    
    def notify_payment_success(self, user_id:  int, amount: float, order_id:  str, balance: float = 0):
        """通知充值成功"""
        
        try:
            self.bot.send_sticker(
                chat_id=user_id,
                sticker="CAACAgIAAxkBAAFA1Bppa6z6nnshjAwlfEK4DHW1Lx74HQACEQUAAs9fiwc1p3GeQTBbeTgE"
            )
        except Exception as e: 
            logging.error(f"❌ 发送贴纸失败: {e}")
        
        text = f"""🎉 <b>Congratulations, recharge successful!</b>

💰 Recharge Amount: <code>{amount:.2f}</code> USDT
💵 Current Balance: <code>{balance:.2f}</code> USDT
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔥 Wishing you prosperous business! """
        
        keyboard = [[InlineKeyboardButton("🏠 Back to Menu", callback_data="back_to_main")]]
        
        try:
            self.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logging.error(f"❌ 发送充值成功通知失败: {e}")

# ================================ Tron区块链客户端 ================================

class TronClient:
    """Tron区块链客户端"""
    
    def __init__(self):
        if Tron is None or HTTPProvider is None:
            raise ImportError("tronpy 未安装，请运行: pip install tronpy")
        
        self.api_keys = [key.strip() for key in Config.TRON_API_KEYS if key.strip()]
        self.api_key_cycle = itertools.cycle(self.api_keys)
        logging.info(f"✅ Tron客户端初始化完成，API Keys数量: {len(self.api_keys)}")
    
    def _get_client(self) -> Tron:
        """获取Tron客户端（轮换API Key）"""
        current_key = next(self.api_key_cycle)
        return Tron(HTTPProvider(api_key=current_key))
    
    def get_account_transactions(self, address: str, min_timestamp: int = None) -> List[Dict]:
        """获取账户交易记录"""
        try:
            # 使用TronGrid API获取交易
            url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20"
            params = {
                'limit': 200,
                'only_confirmed': True,
                'contract_address': SecurityConfig.OFFICIAL_USDT_CONTRACT
            }
            if min_timestamp:
                params['min_timestamp'] = min_timestamp
            
            headers = {'TRON-PRO-API-KEY': next(self.api_key_cycle)}
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            transactions = data.get('data', [])
            
            logging.debug(f"✅ 获取交易记录成功: address={address}, count={len(transactions)}")
            return transactions
            
        except Exception as e:
            logging.error(f"❌ 获取交易记录失败: {e}")
            return []


# ================================ 安全验证器 ================================

class SecurityValidator:
    """安全验证器"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def validate_transaction(self, tx: Dict, target_address: str) -> Optional[Dict]:
        """验证交易是否符合安全要求
        
        返回: {
            'valid': bool,
            'amount': float,
            'tx_id': str,
            'from_address': str,
            'timestamp': int
        } 或 None
        """
        try:
            # 提取交易信息
            tx_id = tx.get('transaction_id')
            token_info = tx.get('token_info', {})
            contract_address = token_info.get('address', '')
            value = tx.get('value', '0')
            to_address = tx.get('to', '')
            from_address = tx.get('from', '')
            timestamp = tx.get('block_timestamp', 0)
            
            # 1.检查是否为USDT合约
            if contract_address != SecurityConfig.OFFICIAL_USDT_CONTRACT:
                logging.debug(f"❌ 非USDT合约: {contract_address}")
                return None
            
            # 2.检查接收地址
            if to_address != target_address:
                logging.debug(f"❌ 接收地址不匹配: {to_address}")
                return None
            
            # 3.计算金额（USDT精度为6）
            amount = float(value) / SecurityConfig.USDT_DECIMALS
            
            # 4.检查最小金额
            if amount < SecurityConfig.MIN_DEPOSIT_AMOUNT:
                logging.warning(f"⚠️ 金额低于最小值: {amount}")
                return None
            
            # 5.检查时效（15分钟内）
            current_timestamp = int(time.time() * 1000)
            if current_timestamp - timestamp > SecurityConfig.BLOCKCHAIN_TIME_LIMIT * 1000:
                logging.debug(f"❌ 交易超时: {timestamp}")
                return None
            
            # 6.检查是否已处理
            if self.db_manager.is_transaction_processed(tx_id):
                logging.debug(f"⚠️ 交易已处理: {tx_id}")
                return None
            
            # 7.检查发送地址黑名单
            if self.db_manager.is_address_blacklisted(from_address):
                logging.warning(f"⚠️ 黑名单地址: {from_address}")
                return None
            
            logging.info(f"✅ 交易验证通过: tx_id={tx_id}, amount={amount}")
            return {
                'valid': True,
                'amount': amount,
                'tx_id': tx_id,
                'from_address': from_address,
                'timestamp': timestamp
            }
            
        except Exception as e:
            logging.error(f"❌ 交易验证失败: {e}")
            return None


# ================================ 订单管理器 ================================

class OrderManager:
    """订单管理器"""
    
    def __init__(self, db_manager: DatabaseManager, bot_manager: BotManager):
        self.db_manager = db_manager
        self.bot_manager = bot_manager
    
    def create_order(self, user_id: int, amount: float, message_id: int) -> Optional[Dict]:
        """创建充值订单"""
        # 生成唯一金额（4位小数）
        exact_amount = self._generate_unique_amount(amount)
        
        # 创建订单
        order_id = self.db_manager.create_order(user_id, amount, exact_amount, message_id)
        
        return {
            'order_id': order_id,
            'exact_amount': exact_amount
        }
    
    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        order = self.db_manager.get_order(order_id)
        if not order or order['status'] != 'pending':
            return False
        
        # 更新订单状态
        self.db_manager.update_order_status(order_id, 'cancelled')
        
        # 删除订单消息
        self.bot_manager.delete_order_message(order['user_id'], order['message_id'])
        
        logging.info(f"✅ 订单已取消: order_id={order_id}")
        return True
    
    def cancel_expired_orders(self):
        """取消过期订单（定时任务）"""
        try:
            pending_orders = self.db_manager.get_pending_orders()
            now = datetime.now()
            
            for order in pending_orders:
                if now > order.get('expires_at', now):
                    # 订单已过期
                    self.db_manager.update_order_status(order['order_id'], 'expired')
                    
                    # 删除订单消息
                    self.bot_manager.delete_order_message(order['user_id'], order['message_id'])
                    
                    logging.info(f"✅ 过期订单已取消: order_id={order['order_id']}")
                    
        except Exception as e:
            logging.error(f"❌ 清理过期订单失败: {e}")
    
    def _generate_unique_amount(self, base_amount: float) -> float:
        """生成唯一金额（4位小数）- 带防重复检查"""
        max_attempts = 100
        for _ in range(max_attempts):
            random_decimal = random.uniform(0.0001, 0.9999)
            exact_amount = round(base_amount + random_decimal, SecurityConfig.DECIMAL_PLACES)
            
            # 检查是否已存在相同金额的pending订单
            existing = self.db_manager.topup.find_one({
                'exact_amount': exact_amount,
                'status':  'pending'
            })
            if not existing:
                return exact_amount
        
        # 兜底：使用时间戳
        timestamp_decimal = (time.time() % 1)
        return round(base_amount + timestamp_decimal, SecurityConfig.DECIMAL_PLACES)

# ================================ 支付处理器 ================================

class PaymentProcessor:
    """支付处理器"""
    
    def __init__(self, db_manager: DatabaseManager, bot_manager: BotManager, 
                 tron_client: TronClient, validator: SecurityValidator):
        self.db_manager = db_manager
        self.bot_manager = bot_manager
        self.tron_client = tron_client
        self.validator = validator
    
        self.processed_tx_ids = set()  # 记录已处理的交易ID
    def process_payments(self):
        """处理支付（主循环）"""
        try:
            # 计算15分钟前的时间戳
            min_timestamp = int((time.time() - SecurityConfig.BLOCKCHAIN_TIME_LIMIT) * 1000)
            
            # 获取交易记录
            transactions = self.tron_client.get_account_transactions(
                Config.DEPOSIT_ADDRESS,
                min_timestamp=min_timestamp
            )
            
            if not transactions:
                return
            
            # 获取待处理订单
            pending_orders = self.db_manager.get_pending_orders()
            
            # 匹配交易和订单
            for tx in transactions:
                # 先获取tx_id，跳过已处理的交易
                tx_id = tx. get('transaction_id')
                if tx_id in self. processed_tx_ids:
                    continue
                
                validated = self.validator. validate_transaction(tx, Config. DEPOSIT_ADDRESS)
                if not validated:  
                    continue
                
                # 标记为已处理（无论是否匹配成功）
                self.processed_tx_ids.add(tx_id)
                
                # 匹配订单
                matched_order = self._match_order(validated['amount'], pending_orders)
                if matched_order:
                    self._complete_order(matched_order, validated)
                    logging.info(f"✅ 交易匹配成功: tx_id={tx_id}, amount={validated['amount']}")
                else:
                    logging.warning(f"⚠️ 交易未匹配订单，已忽略:  tx_id={tx_id}, amount={validated['amount']}")
                    
        except Exception as e:
            logging.error(f"❌ 处理支付失败: {e}")
    
    def _match_order(self, amount: float, orders: List[Dict]) -> Optional[Dict]:
        """匹配订单（按创建时间优先）"""
        sorted_orders = sorted(orders, key=lambda x: x.get('created_at', datetime.max))
        for order in sorted_orders:
            if abs(amount - order['exact_amount']) < SecurityConfig.AMOUNT_TOLERANCE: 
                return order
        return None
    
    def _complete_order(self, order:  Dict, validated: Dict):
        """完成订单"""
        try: 
            from pymongo import ReturnDocument
            order_id = order['order_id']
            user_id = order['user_id']
            amount = validated['amount']
            tx_id = validated['tx_id']
            
            # 🔒 原子操作：锁定订单防止并发重复处理
            locked_order = self.db_manager.topup.find_one_and_update(
                {'order_id': order_id, 'status': 'pending'},
                {'$set': {'status': 'processing'}},
                return_document=ReturnDocument.AFTER
            )
            if not locked_order: 
                logging.warning(f"⚠️ 订单已被处理，跳过:  {order_id}")
                return
            
            # 获取充值前的余额
            old_balance = self.db_manager.get_user_balance(user_id)
            
            # 更新订单状态为completed
            self.db_manager.update_order_status(order_id, 'completed')
            
            # 标记交易已处理
            self.db_manager.mark_transaction_processed(tx_id, order_id, amount)
            
            # 给用户加余额
            self.db_manager.update_user_balance(user_id, amount)
            
            # 更新订单消息
            self.bot_manager.delete_order_message(user_id, order['message_id'])
            
            # 获取更新后的余额
            balance = self.db_manager.get_user_balance(user_id)
            
            # 发送充值成功通知（显示时保留2位小数）
            self.bot_manager.notify_payment_success(user_id, round(amount, 2), order_id, balance)
            
            # 发送充值订单通知到群组
            try:
                # 获取用户信息
                user_info = self.db_manager.users.find_one({'user_id': user_id})
                username = user_info.get('username', 'unknown') if user_info else 'unknown'
                
                # 计算累计充值（使用MongoDB聚合管道高效计算）
                pipeline = [
                    {
                        '$match': {
                            'user_id': user_id,
                            'status': 'completed'
                        }
                    },
                    {
                        '$group': {
                            '_id': None,
                            'total': {
                                '$sum': {
                                    '$ifNull': ['$exact_amount', '$amount']
                                }
                            }
                        }
                    }
                ]
                result = list(self.db_manager.topup.aggregate(pipeline))
                total_recharge = result[0]['total'] if result else 0
                
                # 准备通知数据
                order_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                recharge_notify_data = {
                    'username': username,
                    'user_id': user_id,
                    'order_id': order_id,
                    'order_time': order_time,
                    'amount': amount,
                    'old_balance': old_balance,
                    'new_balance': balance,
                    'total_recharge': total_recharge,
                    'from_address': validated['from_address']
                }
                
                # 发送通知（需要导入通知函数）
                self._send_recharge_notify_to_group(recharge_notify_data)
            except Exception as notify_error:
                logging.error(f"❌ 发送充值订单通知失败: {notify_error}")
            
            logging.info(f"✅ 订单完成: order_id={order_id}, user_id={user_id}, amount={amount}")
            
        except Exception as e:
            logging.error(f"❌ 完成订单失败: {e}")
    
    def _send_recharge_notify_to_group(self, order_data):
        """
        发送充值订单通知到群组
        
        Args:
            order_data (dict): 充值订单数据，包含以下字段:
                - username: 用户名
                - user_id: 用户ID
                - order_id: 订单号
                - order_time: 订单时间
                - amount: 充值金额
                - old_balance: 旧余额
                - new_balance: 新余额
                - total_recharge: 累计充值金额
        """
        # 检查是否配置了通知群
        notify_group = os.getenv('AGENT_ORDER_NOTIFY_GROUP', '').strip()
        if not notify_group:
            return
        
        try:
            # 转换群ID为整数
            group_id = int(notify_group)
            
            # 格式化通知消息
            username_display = f"@{order_data['username']}" if order_data['username'] and order_data['username'] != 'unknown' else f"{order_data['user_id']}"
            
            # 先提取变量避免f-string语法问题
            order_id = order_data['order_id']
            order_time = order_data['order_time']
            user_id = order_data['user_id']
            amount = order_data['amount']
            old_balance = order_data['old_balance']
            new_balance = order_data['new_balance']
            total_recharge = order_data['total_recharge']
            from_address = order_data.get('from_address', 'Unknown')
            
            message = f"""💰 <b>收到了一份 充值订单</b> 💵

<b>👤 用户名: </b> <b>{username_display}</b>
<b>🧾 充值单号: </b> <code>{order_id}</code>
━━━━━━━━━━━━━━━━━━
<b>📅 日期|时间:</b> <b>{order_time}</b>
<b>👤 来自用户:  </b> <b>{user_id}</b>
<b>💵 充值金额:</b> <b>{amount:.2f} USDT</b>
<b>💰 用户旧余额:  </b> <b>{old_balance:.2f} U</b>
<b>💰 用户当前余额: </b> <b>{new_balance:.2f} U</b>
<b>📊 累计充值: </b> <b>{total_recharge:.2f} U</b>
<b>🏦 付款地址: </b>
<code>{from_address}</code>
━━━━━━━━━━━━━━━━━━"""

            # 创建查看交易按钮
            keyboard = [[InlineKeyboardButton("🔍查看交易", url=f"https://tronscan.org/#/address/{from_address}")]]
            
            self.bot_manager.bot.send_message(
                chat_id=group_id,
                text=message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            logging.info(f"✅ 充值订单通知已发送到群组: {group_id}")
            
        except ValueError as e:
            logging.error(f"❌ 群组ID格式错误: {notify_group}, 错误: {e}")
        except Exception as e:
            logging.error(f"❌ 发送充值订单通知到群组失败: {e}")


# ================================ 主支付系统 ================================

class AgentPaymentSystem:
    """代理支付系统"""
    
    def __init__(self):
        # 验证配置
        Config.validate()
        
        # 初始化组件
        self.db_manager = DatabaseManager()
        self.bot_manager = BotManager()
        self.tron_client = TronClient()
        self.validator = SecurityValidator(self.db_manager)
        self.order_manager = OrderManager(self.db_manager, self.bot_manager)
        self.payment_processor = PaymentProcessor(
            self.db_manager, self.bot_manager, 
            self.tron_client, self.validator
        )
        
        # 运行标志
        self.running = False
        self.payment_thread = None
        self.cleanup_thread = None
        
        logging.info("✅ 代理支付系统初始化完成")
    
    def start(self):
        """启动支付系统"""
        if self.running:
            logging.warning("⚠️ 支付系统已在运行")
            return
        
        self.running = True
        
        # 启动支付处理线程
        self.payment_thread = threading.Thread(target=self._payment_loop, daemon=True)
        self.payment_thread.start()
        
        # 启动订单清理线程
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
        
        logging.info("✅ 支付系统已启动")
    
    def stop(self):
        """停止支付系统"""
        self.running = False
        logging.info("✅ 支付系统已停止")
    
    def _payment_loop(self):
        """支付处理循环"""
        logging.info("🔄 支付处理循环已启动")
        while self.running:
            try:
                self.payment_processor.process_payments()
            except Exception as e:
                logging.error(f"❌ 支付处理循环异常: {e}")
            time.sleep(Config.POLL_INTERVAL)
    
    def _cleanup_loop(self):
        """订单清理循环"""
        logging.info("🔄 订单清理循环已启动")
        while self.running:
            try:
                self.order_manager.cancel_expired_orders()
            except Exception as e:
                logging.error(f"❌ 订单清理循环异常: {e}")
            time.sleep(Config.ORDER_CLEANUP_INTERVAL)
    
    def create_order(self, user_id: int, amount: float, message_id: int) -> Optional[Dict]:
        """创建充值订单（外部接口）"""
        return self.order_manager.create_order(user_id, amount, message_id)
    
    def cancel_order(self, order_id: str) -> bool:
        """取消订单（外部接口）"""
        return self.order_manager.cancel_order(order_id)


# ================================ 辅助函数 ================================

# 全局支付系统实例
_payment_system_instance: Optional[AgentPaymentSystem] = None


def get_payment_system() -> AgentPaymentSystem:
    """获取支付系统单例"""
    global _payment_system_instance
    if _payment_system_instance is None:
        _payment_system_instance = AgentPaymentSystem()
    return _payment_system_instance


def create_topup_order(user_id: int, amount: float, message_id: int) -> Optional[Dict]:
    """创建充值订单（便捷函数）"""
    try:
        payment_system = get_payment_system()
        return payment_system.create_order(user_id, amount, message_id)
    except Exception as e:
        logging.error(f"❌ 创建充值订单失败: {e}")
        return None


# ================================ 主程序 ================================

if __name__ == '__main__':
    # 测试支付系统
    try:
        payment_system = get_payment_system()
        payment_system.start()
        
        logging.info("✅ 支付系统测试启动成功")
        logging.info("按 Ctrl+C 停止...")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logging.info("⏹️ 收到停止信号")
        payment_system.stop()
    except Exception as e:
        logging.error(f"❌ 支付系统测试失败: {e}")
        import traceback
        traceback.print_exc()