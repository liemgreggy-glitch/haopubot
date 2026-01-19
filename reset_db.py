# 创建文件: reset_db.py
import os
import pymongo
from dotenv import load_dotenv

load_dotenv()

# 连接数据库
client = pymongo.MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("MONGO_DB_BOT")]

def reset_all_data():
    """重置所有数据"""
    print("⚠️ 即将清空所有数据，5秒后开始...")
    import time
    time.sleep(5)
    
    collections_to_clear = [
        'user', 'gmjlu', 'topup', 'agents', 'qukuai'
    ]
    
    for collection_name in collections_to_clear:
        result = db[collection_name].delete_many({})
        print(f"✅ 清空 {collection_name}: 删除了 {result.deleted_count} 条记录")

def reset_user_balances():
    """重置所有用户余额为0"""
    result = db.user.update_many(
        {},
        {"$set": {"USDT": 0, "zgje": 0, "zgsl": 0}}
    )
    print(f"✅ 重置了 {result.modified_count} 个用户的余额")

def reset_specific_tenant(tenant):
    """重置特定租户的数据"""
    collections = ['user', 'gmjlu', 'topup']
    
    for collection_name in collections:
        result = db[collection_name].delete_many({"tenant": tenant})
        print(f"✅ 删除租户 {tenant} 在 {collection_name} 的 {result.deleted_count} 条记录")

def show_stats():
    """显示数据库统计"""
    stats = {}
    collections = ['user', 'gmjlu', 'topup', 'agents']
    
    for collection_name in collections:
        count = db[collection_name].count_documents({})
        stats[collection_name] = count
        print(f"📊 {collection_name}: {count} 条记录")
    
    return stats

if __name__ == "__main__":
    print("🗄️ 数据库管理工具")
    print("1. 查看统计")
    print("2. 重置用户余额")
    print("3. 重置特定租户")
    print("4. 重置所有数据 (危险)")
    
    choice = input("请选择操作 (1-4): ")
    
    if choice == "1":
        show_stats()
    elif choice == "2":
        reset_user_balances()
    elif choice == "3":
        tenant = input("输入租户名 (如: agent:agent_20251027_234957): ")
        reset_specific_tenant(tenant)
    elif choice == "4":
        confirm = input("确认重置所有数据？输入 'YES' 确认: ")
        if confirm == "YES":
            reset_all_data()
        else:
            print("❌ 操作已取消")
    else:
        print("❌ 无效选择")