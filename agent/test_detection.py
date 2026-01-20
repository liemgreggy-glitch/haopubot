#!/usr/bin/env python3
"""
测试账号检测模块
Test account detection module

使用方法 / Usage:
    python3 test_detection.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from account_detector import ProxyManager, AccountDetector, BatchDetector


def test_proxy_manager():
    """测试代理管理器"""
    print("=" * 60)
    print("测试代理管理器 / Testing ProxyManager")
    print("=" * 60)
    
    # Create proxy manager
    pm = ProxyManager('proxy.txt')
    print(f"✅ ProxyManager 创建成功")
    print(f"   已加载 {len(pm.proxies)} 个代理")
    
    # Test parsing different formats
    test_proxies = [
        "socks5://127.0.0.1:1080",
        "socks5://user:pass@proxy.example.com:1080",
        "socks4://127.0.0.1:1080",
        "http://127.0.0.1:8080",
        "http://user:pass@proxy.example.com:8080",
        "127.0.0.1:1080",
        "192.168.1.1:7890:admin:password"
    ]
    
    print("\n✅ 测试代理解析:")
    success_count = 0
    for proxy_str in test_proxies:
        parsed = pm.parse_proxy(proxy_str)
        if parsed:
            print(f"   ✓ {proxy_str}")
            print(f"      → 类型={parsed['proxy_type']}, 地址={parsed['addr']}, 端口={parsed['port']}")
            if parsed['username']:
                print(f"      → 用户={parsed['username']}")
            success_count += 1
        else:
            print(f"   ✗ 解析失败: {proxy_str}")
    
    print(f"\n   成功解析: {success_count}/{len(test_proxies)}")
    return success_count == len(test_proxies)


def test_keyword_matching():
    """测试关键词匹配"""
    print("\n" + "=" * 60)
    print("测试关键词匹配 / Testing Keyword Matching")
    print("=" * 60)
    
    from account_detector import NORMAL_KEYWORDS, BANNED_KEYWORDS, FROZEN_KEYWORDS
    
    # Test cases
    test_cases = [
        # Normal cases
        ("Good news, no limits on your account!", "normal"),
        ("好消息，您的账户没有任何限制", "normal"),
        ("Хорошие новости, нет ограничений", "normal"),
        
        # Banned cases
        ("Your account is permanently limited", "banned"),
        ("账号已永久受限", "banned"),
        ("Ваш аккаунт навсегда ограничен", "banned"),
        
        # Frozen cases
        ("Your account is temporarily restricted", "frozen"),
        ("账号暂时受限", "frozen"),
        ("Ваш аккаунт временно ограничен", "frozen"),
    ]
    
    # Create detector to test matching
    from dotenv import load_dotenv
    load_dotenv()
    
    api_id = int(os.getenv('API_ID', '0'))
    api_hash = os.getenv('API_HASH', '')
    
    if api_id and api_hash:
        pm = ProxyManager('proxy.txt')
        detector = AccountDetector(api_id, api_hash, pm)
        
        print("\n✅ 测试消息分类:")
        success_count = 0
        for message, expected in test_cases:
            result = detector._match_keywords(message)
            status = "✓" if result == expected else "✗"
            print(f"   {status} {message[:50]}...")
            print(f"      → 预期: {expected}, 实际: {result}")
            if result == expected:
                success_count += 1
        
        print(f"\n   匹配成功: {success_count}/{len(test_cases)}")
        return success_count == len(test_cases)
    else:
        print("⚠️  跳过（未配置 API_ID 和 API_HASH）")
        return True


def test_configuration():
    """测试配置"""
    print("\n" + "=" * 60)
    print("测试配置 / Testing Configuration")
    print("=" * 60)
    
    from dotenv import load_dotenv
    load_dotenv('.env')
    
    configs = [
        ('API_ID', os.getenv('API_ID')),
        ('API_HASH', os.getenv('API_HASH')),
        ('BAD_ACCOUNT_GROUP_ID', os.getenv('BAD_ACCOUNT_GROUP_ID')),
        ('BASE_PROTOCOL_PATH', os.getenv('BASE_PROTOCOL_PATH')),
        ('ENABLE_ACCOUNT_DETECTION', os.getenv('ENABLE_ACCOUNT_DETECTION', 'true'))
    ]
    
    print("\n✅ 环境变量检查:")
    all_configured = True
    for key, value in configs:
        if value:
            print(f"   ✓ {key}: 已配置")
        else:
            print(f"   ⚠  {key}: 未配置")
            if key in ['API_ID', 'API_HASH']:
                all_configured = False
    
    if not all_configured:
        print("\n   ⚠️  检测功能需要 API_ID 和 API_HASH")
        print("      请参考 .env.example 配置环境变量")
    
    return True


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("账号检测模块测试 / Account Detection Module Test")
    print("=" * 60)
    
    results = []
    
    # Test 1: Proxy Manager
    try:
        results.append(("ProxyManager", test_proxy_manager()))
    except Exception as e:
        print(f"❌ ProxyManager 测试失败: {e}")
        results.append(("ProxyManager", False))
    
    # Test 2: Keyword Matching
    try:
        results.append(("Keyword Matching", test_keyword_matching()))
    except Exception as e:
        print(f"❌ 关键词匹配测试失败: {e}")
        results.append(("Keyword Matching", False))
    
    # Test 3: Configuration
    try:
        results.append(("Configuration", test_configuration()))
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        results.append(("Configuration", False))
    
    # Print summary
    print("\n" + "=" * 60)
    print("测试总结 / Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {status}: {name}")
    
    print(f"\n   总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！")
        return 0
    else:
        print("\n⚠️  部分测试失败，请检查配置")
        return 1


if __name__ == '__main__':
    sys.exit(main())
