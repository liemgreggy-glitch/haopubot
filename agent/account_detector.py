"""
账号售后检测模块
After-sales account quality detection module

功能：
1. 连接代理
2. 登录账户
3. 访问 @SpamBot 获取回复
4. 多语言关键词匹配判断账号状态
5. 并发检测（30线程）
"""

import os
import asyncio
import logging
import time
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberBannedError,
    AuthKeyUnregisteredError,
    UserDeactivatedError,
    UserDeactivatedBanError
)
import json

# 多语言关键词匹配
NORMAL_KEYWORDS = [
    'good news', 'no limits', 'no restrictions',
    '好消息', '没有限制', '没有任何限制',
    'хорошие новости', 'ограничений нет', 'нет ограничений',
    'خبر خوب', 'بدون محدودیت',
    'buenas noticias', 'sin límites',
    'bonne nouvelle', 'aucune limite',
]

BANNED_KEYWORDS = [
    'permanently limited', 'permanently restricted',
    '永久限制', '永久受限',
    'навсегда ограничен',
    'محدودیت دائمی',
]

FROZEN_KEYWORDS = [
    'limited', 'restricted', 'temporarily',
    '限制', '受限', '暂时',
    'ограничен', 'временно',
    'محدود', 'موقت',
    'limitado', 'restringido',
    'limité', 'restreint',
]


class ProxyManager:
    """代理管理器"""
    
    def __init__(self, proxy_file='proxy.txt'):
        self.proxy_file = os.path.join(os.path.dirname(__file__), proxy_file)
        self.proxies = []
        self.current_index = 0
        self.load_proxies()
    
    def load_proxies(self):
        """从文件加载代理"""
        if not os.path.exists(self.proxy_file):
            logging.warning(f"代理文件不存在: {self.proxy_file}")
            return
        
        try:
            with open(self.proxy_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                proxy = self.parse_proxy(line)
                if proxy:
                    self.proxies.append(proxy)
            
            logging.info(f"✅ 加载了 {len(self.proxies)} 个代理")
        except Exception as e:
            logging.error(f"❌ 加载代理失败: {e}")
    
    def parse_proxy(self, line: str) -> Dict:
        """
        解析代理配置
        支持格式:
        - socks5://127.0.0.1:1080
        - socks5://user:pass@127.0.0.1:1080
        - http://127.0.0.1:8080
        - 127.0.0.1:1080
        - 127.0.0.1:1080:user:pass
        """
        try:
            # 处理 scheme://[user:pass@]host:port 格式
            if '://' in line:
                scheme, rest = line.split('://', 1)
                
                # 处理认证信息
                if '@' in rest:
                    auth, addr = rest.split('@', 1)
                    username, password = auth.split(':', 1)
                else:
                    username, password = None, None
                    addr = rest
                
                # 解析主机和端口
                host, port = addr.rsplit(':', 1)
                
                return {
                    'proxy_type': scheme,  # socks5, socks4, http
                    'addr': host,
                    'port': int(port),
                    'username': username,
                    'password': password
                }
            
            # 处理 host:port 或 host:port:user:pass 格式
            parts = line.split(':')
            if len(parts) == 2:
                return {
                    'proxy_type': 'socks5',
                    'addr': parts[0],
                    'port': int(parts[1]),
                    'username': None,
                    'password': None
                }
            elif len(parts) == 4:
                return {
                    'proxy_type': 'socks5',
                    'addr': parts[0],
                    'port': int(parts[1]),
                    'username': parts[2],
                    'password': parts[3]
                }
        except Exception as e:
            logging.error(f"解析代理失败: {line}, 错误: {e}")
        
        return None
    
    def get_next_proxy(self) -> Dict:
        """获取下一个代理（轮询）"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxies)
        return proxy
    
    def get_all_proxies(self) -> List[Dict]:
        """获取所有代理"""
        return self.proxies.copy()


class AccountDetector:
    """账号检测器"""
    
    def __init__(self, api_id: int, api_hash: str, proxy_manager: ProxyManager):
        self.api_id = api_id
        self.api_hash = api_hash
        self.proxy_manager = proxy_manager
    
    async def check_account(self, session_file: str, json_file: str, max_proxy_retries: int = 3) -> Tuple[str, str]:
        """
        检测单个账号
        
        Returns:
            (status, message)
            status: 'normal', 'banned', 'frozen', 'unknown'
        """
        logging.info(f"📝 开始检测账号: {session_file}")
        
        # 尝试使用代理
        for retry in range(max_proxy_retries):
            proxy = self.proxy_manager.get_next_proxy() if retry < max_proxy_retries - 1 else None
            
            if proxy:
                logging.info(f"🌐 使用代理: {proxy.get('addr')}:{proxy.get('port')} (尝试 {retry+1}/{max_proxy_retries})")
            else:
                logging.info(f"🔗 使用直连 (尝试 {retry+1}/{max_proxy_retries})")
            
            try:
                result = await self._check_with_proxy(session_file, json_file, proxy)
                status, message = result
                logging.info(f"✅ 检测完成: {session_file} -> 状态: {status}")
                return result
            except Exception as e:
                logging.warning(f"⚠️ 代理检测失败 (retry {retry+1}/{max_proxy_retries}): {e}")
                if retry >= max_proxy_retries - 1:
                    # 所有代理都失败，使用本地直连
                    try:
                        logging.info(f"🔄 所有代理失败，尝试本地直连...")
                        result = await self._check_with_proxy(session_file, json_file, None)
                        status, message = result
                        logging.info(f"✅ 本地直连成功: {session_file} -> 状态: {status}")
                        return result
                    except Exception as e2:
                        logging.error(f"❌ 本地直连也失败: {e2}")
                        return 'unknown', str(e2)
        
        return 'unknown', '连接失败'
    
    async def _check_with_proxy(self, session_file: str, json_file: str, proxy: Dict = None) -> Tuple[str, str]:
        """使用指定代理检测账号"""
        client = None
        
        try:
            logging.debug(f"🔧 创建Telegram客户端: {session_file}")
            # 创建客户端
            client = TelegramClient(
                session_file,
                self.api_id,
                self.api_hash,
                proxy=proxy
            )
            
            # 连接
            logging.debug(f"🔌 正在连接Telegram服务器...")
            await client.connect()
            logging.debug(f"✅ 已连接到Telegram服务器")
            
            # 检查是否已登录
            logging.debug(f"🔑 检查Session授权状态...")
            if not await client.is_user_authorized():
                logging.warning(f"❌ Session未授权: {session_file}")
                return 'banned', 'Session未授权'
            
            # 获取当前用户信息（检测是否被封禁/冻结）
            try:
                logging.debug(f"👤 正在获取用户信息...")
                me = await client.get_me()
                logging.debug(f"✅ 成功获取用户信息: {me.id}")
            except UserDeactivatedError as e:
                # 账号已被冻结/停用
                logging.warning(f"⚠️ 账号已冻结: UserDeactivatedError")
                return 'frozen', '账号已冻结 (UserDeactivatedError)'
            except UserDeactivatedBanError as e:
                # 账号已被永久封禁
                logging.warning(f"❌ 账号已封禁: UserDeactivatedBanError")
                return 'banned', '账号已封禁 (UserDeactivatedBanError)'
            except AuthKeyUnregisteredError as e:
                # 会话已失效，账号可能被冻结
                logging.warning(f"⚠️ 会话失效: AuthKeyUnregisteredError")
                return 'frozen', '会话失效 (AuthKeyUnregisteredError)'
            except PhoneNumberBannedError as e:
                # 手机号已封禁
                logging.warning(f"❌ 手机号已封禁: PhoneNumberBannedError")
                return 'banned', '手机号已封禁 (PhoneNumberBannedError)'
            except Exception as e:
                error_str = str(e).lower()
                logging.warning(f"⚠️ 获取用户信息异常: {e}")
                # 检查错误消息中是否包含冻结相关关键词
                if 'deactivat' in error_str or 'unregister' in error_str:
                    logging.warning(f"⚠️ 检测到冻结关键词: {error_str}")
                    return 'frozen', f'账号可能被冻结: {str(e)}'
                return 'unknown', f'获取用户信息失败: {str(e)}'
            
            # 访问 @SpamBot
            try:
                logging.debug(f"🤖 开始与SpamBot对话...")
                async with client.conversation('SpamBot') as conv:
                    # 发送 /start
                    logging.debug(f"📤 发送 /start 到 SpamBot...")
                    await conv.send_message('/start')
                    
                    # 等待回复（最多10秒）
                    logging.debug(f"⏳ 等待SpamBot回复 (最多10秒)...")
                    response = await asyncio.wait_for(conv.get_response(), timeout=10)
                    response_text = response.message.lower()
                    
                    logging.debug(f"📥 收到SpamBot回复: {response_text[:100]}...")
                    
                    # 关键词匹配
                    status = self._match_keywords(response_text)
                    logging.info(f"🔍 关键词匹配结果: {status}")
                    return status, response_text
            except asyncio.TimeoutError:
                logging.warning(f"⏱️ SpamBot响应超时")
                return 'unknown', 'SpamBot无响应'
            except Exception as e:
                logging.error(f"❌ SpamBot检测失败: {e}")
                return 'unknown', f'SpamBot检测失败: {str(e)}'
        
        except Exception as e:
            raise  # 向上抛出异常以便重试
        
        finally:
            if client:
                logging.debug(f"🔌 断开Telegram连接")
                await client.disconnect()
    
    def _match_keywords(self, text: str) -> str:
        """
        多语言关键词匹配
        
        Returns:
            'normal', 'banned', 'frozen'
        """
        text_lower = text.lower()
        
        logging.debug(f"🔍 开始关键词匹配，文本长度: {len(text_lower)}")
        
        # 优先匹配封禁（永久限制）
        for keyword in BANNED_KEYWORDS:
            if keyword.lower() in text_lower:
                logging.debug(f"❌ 匹配到封禁关键词: '{keyword}'")
                return 'banned'
        
        # 然后匹配冻结（临时限制）
        for keyword in FROZEN_KEYWORDS:
            if keyword.lower() in text_lower:
                logging.debug(f"⚠️ 匹配到冻结关键词: '{keyword}'")
                return 'frozen'
        
        # 最后匹配正常
        for keyword in NORMAL_KEYWORDS:
            if keyword.lower() in text_lower:
                logging.debug(f"✅ 匹配到正常关键词: '{keyword}'")
                return 'normal'
        
        # 无法匹配
        logging.debug(f"❓ 未匹配到任何关键词，返回unknown")
        return 'unknown'


class BatchDetector:
    """批量检测器"""
    
    def __init__(self, api_id: int, api_hash: str, proxy_file: str = 'proxy.txt', max_workers: int = 30):
        self.api_id = api_id
        self.api_hash = api_hash
        self.proxy_manager = ProxyManager(proxy_file)
        self.max_workers = max_workers
        self.detector = AccountDetector(api_id, api_hash, self.proxy_manager)
    
    def detect_accounts(self, accounts: List[Dict], progress_callback=None) -> Dict:
        """
        并发检测多个账号
        
        Args:
            accounts: [{'phone': '+86xxx', 'session': 'path/to/session', 'json': 'path/to/json'}, ...]
            progress_callback: 进度回调函数 (current, total, results)
        
        Returns:
            {
                'normal': [...],
                'banned': [...],
                'frozen': [...],
                'unknown': [...]
            }
        """
        results = {
            'normal': [],
            'banned': [],
            'frozen': [],
            'unknown': []
        }
        
        total = len(accounts)
        current = 0
        
        logging.info(f"🚀 开始批量检测 {total} 个账号，并发数: {self.max_workers}")
        logging.info(f"📊 代理池大小: {len(self.proxy_manager.proxies)}")
        
        # 使用线程池并发检测
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            future_to_account = {}
            logging.info(f"📤 提交所有检测任务到线程池...")
            for account in accounts:
                future = executor.submit(
                    self._detect_sync,
                    account['session'],
                    account['json']
                )
                future_to_account[future] = account
            
            logging.info(f"✅ 已提交 {len(future_to_account)} 个检测任务，等待执行...")
            
            # 处理完成的任务
            for future in as_completed(future_to_account):
                account = future_to_account[future]
                current += 1
                
                try:
                    status, message = future.result()
                    
                    # 添加到对应结果列表
                    result_item = {
                        'phone': account['phone'],
                        'session': account['session'],
                        'json': account['json'],
                        'message': message
                    }
                    # 保留 db_id 如果存在
                    if 'db_id' in account:
                        result_item['db_id'] = account['db_id']
                    
                    results[status].append(result_item)
                    
                    # 使用表情符号显示状态
                    status_emoji = {
                        'normal': '✅',
                        'banned': '❌',
                        'frozen': '⚠️',
                        'unknown': '❓'
                    }.get(status, '❓')
                    
                    logging.info(f"[{current}/{total}] {status_emoji} {account['phone']}: {status}")
                    
                except Exception as e:
                    logging.error(f"❌ 检测失败 [{current}/{total}] {account['phone']}: {e}")
                    result_item = {
                        'phone': account['phone'],
                        'session': account['session'],
                        'json': account['json'],
                        'message': str(e)
                    }
                    # 保留 db_id 如果存在
                    if 'db_id' in account:
                        result_item['db_id'] = account['db_id']
                    
                    results['unknown'].append(result_item)
                
                # 进度回调
                if progress_callback:
                    try:
                        progress_callback(current, total, results)
                    except Exception as e:
                        logging.error(f"进度回调失败: {e}")
        
        # 输出最终统计
        logging.info(f"")
        logging.info(f"{'='*60}")
        logging.info(f"📊 批量检测完成！总计: {total} 个账号")
        logging.info(f"✅ 正常: {len(results['normal'])} 个")
        logging.info(f"❌ 封禁: {len(results['banned'])} 个")
        logging.info(f"⚠️ 冻结: {len(results['frozen'])} 个")
        logging.info(f"❓ 未知: {len(results['unknown'])} 个")
        logging.info(f"{'='*60}")
        logging.info(f"")
        
        return results
    
    def _detect_sync(self, session_file: str, json_file: str) -> Tuple[str, str]:
        """同步包装的异步检测方法"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self.detector.check_account(session_file, json_file)
            )
        finally:
            loop.close()


def test_detector():
    """测试检测器"""
    # 从环境变量读取配置
    from dotenv import load_dotenv
    load_dotenv()
    
    api_id = int(os.getenv('API_ID', '0'))
    api_hash = os.getenv('API_HASH', '')
    
    if not api_id or not api_hash:
        print("❌ 缺少 API_ID 或 API_HASH 环境变量")
        return
    
    # 创建批量检测器
    detector = BatchDetector(api_id, api_hash)
    
    # 测试账号列表（需要替换为实际路径）
    test_accounts = [
        {
            'phone': '+8613800001',
            'session': '/path/to/+8613800001.session',
            'json': '/path/to/+8613800001.json'
        }
    ]
    
    def progress_callback(current, total, results):
        print(f"\n进度: {current}/{total}")
        print(f"✅ 正常: {len(results['normal'])}")
        print(f"❌ 封禁: {len(results['banned'])}")
        print(f"⚠️ 冻结: {len(results['frozen'])}")
        print(f"❓ 未知: {len(results['unknown'])}")
    
    # 执行检测
    results = detector.detect_accounts(test_accounts, progress_callback)
    
    print("\n最终结果:")
    print(f"✅ 正常: {len(results['normal'])} 个")
    print(f"❌ 封禁: {len(results['banned'])} 个")
    print(f"⚠️ 冻结: {len(results['frozen'])} 个")
    print(f"❓ 未知: {len(results['unknown'])} 个")


if __name__ == '__main__':
    test_detector()
