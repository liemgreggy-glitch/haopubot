"""
账号售后检测模块
After-sales account quality detection module

功能：
1.连接代理
2.登录账户
3.向收藏夹发送随机消息检测账号状态
4.并发检测（30线程）
5.超时保护，防止卡死
6.保护原始session文件，检测用临时复制文件

状态定义：
- 存活(normal): 能连接且能发消息到收藏夹
- 冻结(frozen): 能连接但无法发消息到收藏夹
- 封禁(banned): 无法连接Telegram
- 未知(unknown): 以上3种都无法验证
"""

import os
import asyncio
import logging
import time
import random
import string
import shutil
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneNumberBannedError,
    AuthKeyUnregisteredError,
    UserDeactivatedError,
    UserDeactivatedBanError,
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError
)
import json


# 封禁账号关键词 - 无法连接Telegram
BANNED_KEYWORDS = [
    'permanently banned',
    'account has been frozen permanently',
    'permanently restricted',
    'banned permanently',
    'permanent ban',
    'account was blocked',
    'blocked for violations',
    'terms of service',
    'banned',
    'suspended',
    'deactivated',
    'deleted',
    'account is banned',
    'this account is no longer accessible',
    'phone number banned',
    'forbidden',
    'access denied',
    'user deactivated',
    'auth key unregistered',
    '永久限制',
    '永久封禁',
    '��封禁',
    '账号已封',
    '无法登录',
    'заблокирован', 'навсегда ограничен',
    'مسدود شده',
]

# 冻结账号关键词 - 能连接但无法发消息
FROZEN_KEYWORDS = [
    'limited',
    'restricted',
    'temporarily',
    'temporary restriction',
    'spam',
    'flood wait',
    'too many requests',
    'try again later',
    'sending messages is restricted',
    'chat write forbidden',
    'user is restricted',
    'slowmode',
    '限制',
    '受限',
    '暂时',
    '临时限制',
    '发送受限',
    'ограничен', 'временно',
    'محدود', 'موقت',
    'limitado', 'restringido',
    'limité', 'restreint',
]


def generate_random_message():
    """生成随机检测消息，避免风控"""
    symbols = ['🔍', '✨', '💫', '⭐', '🌟', '💡', '🔹', '🔸', '▪️', '▫️', '◽', '◾', '🎯', '🎲', '🎪']
    chars = string.ascii_letters + string.digits
    random_str = ''.join(random.choices(chars, k=random.randint(4, 8)))
    random_symbol = random.choice(symbols)
    timestamp = str(int(time.time()))[-4:]
    return f"{random_symbol}{random_str}{timestamp}"


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
    
    def parse_proxy(self, line:  str) -> Dict:
        """解析代理配置"""
        try:
            if '://' in line:
                scheme, rest = line.split('://', 1)
                if '@' in rest:
                    auth, addr = rest.split('@', 1)
                    username, password = auth.split(':', 1)
                else:
                    username, password = None, None
                    addr = rest
                host, port = addr.rsplit(':', 1)
                return {
                    'proxy_type': scheme,
                    'addr': host,
                    'port': int(port),
                    'username': username,
                    'password': password
                }
            
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
    """账号检测器 - 通过向收藏夹发消息检测状态"""
    
    def __init__(self, api_id: int, api_hash: str, proxy_manager: ProxyManager):
        self.api_id = api_id
        self.api_hash = api_hash
        self.proxy_manager = proxy_manager
    
    async def check_account(self, session_file: str, json_file: str, max_proxy_retries: int = 2) -> Tuple[str, str]:
        """
        检测单个账号
        
        检测逻辑：
        1.复制session文件用于检测（保护原始文件）
        2.尝试连接 -> 失败则封禁
        3.尝试发消息到收藏夹 -> 成功则存活，失败则冻结
        
        Returns:
            (status, message)
            status: 'normal', 'banned', 'frozen', 'unknown'
        """
        logging.debug(f"📝 开始检测账号:  {session_file}")
        
        for retry in range(max_proxy_retries):
            proxy = self.proxy_manager.get_next_proxy() if self.proxy_manager.proxies else None
            
            try:
                result = await self._check_with_proxy(session_file, json_file, proxy)
                return result
            except Exception as e: 
                logging.warning(f"⚠️ 检测失败 (retry {retry+1}/{max_proxy_retries}): {e}")
                if retry >= max_proxy_retries - 1:
                    return self._classify_error(str(e))
        
        return 'unknown', '连接失败'
    
    def _classify_error(self, error_msg: str) -> Tuple[str, str]:
        """根据错误信息分类状态"""
        error_lower = error_msg.lower()
        
        for keyword in BANNED_KEYWORDS: 
            if keyword.lower() in error_lower:
                return 'banned', error_msg
        
        for keyword in FROZEN_KEYWORDS:
            if keyword.lower() in error_lower:
                return 'frozen', error_msg
        
        return 'unknown', error_msg
    
    async def _check_with_proxy(self, session_file: str, json_file: str, proxy: Dict = None) -> Tuple[str, str]:
        """使用指定代理检测账号 - 带超时保护，使用临时session文件"""
        client = None
        temp_session = None
        temp_session_path = None
        
        try: 
            # 复制session文件用于检测，保护原始文件不被Telethon修改
            original_session_path = session_file + '.session'
            temp_session = session_file + f'_detect_{int(time.time() * 1000)}'
            temp_session_path = temp_session + '.session'
            
            try:
                if os.path.exists(original_session_path):
                    shutil.copy2(original_session_path, temp_session_path)
                else:
                    # 原始文件不存在
                    return 'banned', f'Session文件不存在: {original_session_path}'
            except Exception as copy_err:
                logging.warning(f"复制session失败: {copy_err}, 使用原文件")
                temp_session = session_file
                temp_session_path = None
            
            client = TelegramClient(
                temp_session,
                self.api_id,
                self.api_hash,
                proxy=proxy,
                timeout=10,
                connection_retries=1
            )
            
            # 连接超时10秒
            await asyncio.wait_for(client.connect(), timeout=10)
            
            # 检查授权超时5秒
            try:
                authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=5)
                if not authorized: 
                    return 'banned', 'Session未授权，账号可能已封禁'
            except asyncio.TimeoutError:
                return 'unknown', '授权检查超时'
            
            # 获取用户信息超时5秒
            try: 
                me = await asyncio.wait_for(client.get_me(), timeout=5)
            except asyncio.TimeoutError:
                return 'unknown', '获取用户信息超时'
            except UserDeactivatedError as e:
                return 'frozen', f'账号已冻结: {str(e)}'
            except UserDeactivatedBanError as e:
                return 'banned', f'账号已封禁: {str(e)}'
            except AuthKeyUnregisteredError as e: 
                return 'banned', f'会话已失效: {str(e)}'
            except PhoneNumberBannedError as e:
                return 'banned', f'手机号已封禁: {str(e)}'
            except Exception as e:
                return self._classify_error(str(e))
            
            # 发送消息超时10秒
            try:
                test_msg = generate_random_message()
                
                sent = await asyncio.wait_for(
                    client.send_message('me', test_msg),
                    timeout=10
                )
                
                # 删除消息（不阻塞）
                try:
                    await asyncio.wait_for(sent.delete(), timeout=3)
                except: 
                    pass
                
                return 'normal', '账号正常，可发送消息'
                
            except asyncio.TimeoutError:
                return 'frozen', '发送消息超时'
            except FloodWaitError as e:
                return 'frozen', f'发送频率受限，需等待 {e.seconds} 秒'
            except ChatWriteForbiddenError as e:
                return 'frozen', f'无法发送消息:  {str(e)}'
            except UserBannedInChannelError as e:
                return 'frozen', f'用户被限制:  {str(e)}'
            except Exception as send_err:
                error_msg = str(send_err).lower()
                
                for keyword in BANNED_KEYWORDS: 
                    if keyword.lower() in error_msg:
                        return 'banned', f'发送失败(封禁): {str(send_err)}'
                
                for keyword in FROZEN_KEYWORDS:
                    if keyword.lower() in error_msg:
                        return 'frozen', f'发送失败(冻结): {str(send_err)}'
                
                return 'frozen', f'无法发送消息: {str(send_err)}'
        
        except asyncio.TimeoutError:
            return 'unknown', '连接超时'
        except UserDeactivatedError as e: 
            return 'frozen', f'账号已冻结: {str(e)}'
        except UserDeactivatedBanError as e:
            return 'banned', f'账号已封禁: {str(e)}'
        except AuthKeyUnregisteredError as e:
            return 'banned', f'会话已失效: {str(e)}'
        except PhoneNumberBannedError as e:
            return 'banned', f'手机号已封禁: {str(e)}'
        except Exception as e:
            return self._classify_error(str(e))
        
        finally: 
            # 断开连接
            if client: 
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=3)
                except:
                    pass
            
            # 删除临时检测文件
            if temp_session_path and os.path.exists(temp_session_path):
                try:
                    os.remove(temp_session_path)
                except:
                    pass


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
                'normal': [...],   # 存活：能发消息
                'banned': [...],   # 封禁：无法连接
                'frozen': [...],   # 冻结：能连接但无法发消息
                'unknown': [...]   # 未知：无法确定
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
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_account = {}
            for account in accounts:
                future = executor.submit(
                    self._detect_sync,
                    account['session'],
                    account['json']
                )
                future_to_account[future] = account
            
            for future in as_completed(future_to_account):
                account = future_to_account[future]
                current += 1
                
                try:
                    status, message = future.result(timeout=60)
                    
                    result_item = {
                        'phone': account['phone'],
                        'session': account['session'],
                        'json': account['json'],
                        'message': message
                    }
                    if 'db_id' in account:
                        result_item['db_id'] = account['db_id']
                    
                    results[status].append(result_item)
                    
                    status_emoji = {
                        'normal': '✅',
                        'banned':  '❌',
                        'frozen':  '⚠️',
                        'unknown': '❓'
                    }.get(status, '❓')
                    
                    logging.info(f"[{current}/{total}] {status_emoji} {account['phone']}: {status}")
                    
                except Exception as e:
                    logging.error(f"❌ 检测失败 [{current}/{total}] {account['phone']}: {e}")
                    result_item = {
                        'phone': account['phone'],
                        'session': account['session'],
                        'json': account['json'],
                        'message':  str(e)
                    }
                    if 'db_id' in account:
                        result_item['db_id'] = account['db_id']
                    results['unknown'].append(result_item)
                
                # 进度回调
                if progress_callback:
                    try:
                        progress_callback(current, total, results)
                    except: 
                        pass
        
        logging.info(f"{'='*60}")
        logging.info(f"📊 批量检测完成！总计:  {total} 个账号")
        logging.info(f"✅ 存活:  {len(results['normal'])} 个 (能发消息)")
        logging.info(f"❌ 封禁: {len(results['banned'])} 个 (无法连接)")
        logging.info(f"⚠️ 冻结: {len(results['frozen'])} 个 (能连接但无法发消息)")
        logging.info(f"❓ 未知: {len(results['unknown'])} 个")
        logging.info(f"{'='*60}")
        
        return results
    
    def _detect_sync(self, session_file: str, json_file: str) -> Tuple[str, str]:
        """同步包装的异步检测方法 - 带超时保护"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # 单个账号最多30秒超时
            return loop.run_until_complete(
                asyncio.wait_for(
                    self.detector.check_account(session_file, json_file),
                    timeout=30
                )
            )
        except asyncio.TimeoutError:
            logging.warning(f"⏱️ 检测超时:  {session_file}")
            return 'unknown', '检测超时(30秒)'
        except Exception as e:
            logging.error(f"❌ 检测异常: {e}")
            return 'unknown', f'检测异常: {str(e)}'
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending: 
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except:
                pass
            try:
                loop.close()
            except:
                pass
            asyncio.set_event_loop(None)


if __name__ == '__main__':
    print("账号检测模块")
    print("状态定义：")
    print("  ✅ 存活(normal): 能连接且能发消息到收藏夹")
    print("  ⚠️ 冻结(frozen): 能连接但无法发消息到收藏夹")
    print("  ❌ 封禁(banned): 无法连接Telegram")
    print("  ❓ 未知(unknown): 以上3种都无法验证")
