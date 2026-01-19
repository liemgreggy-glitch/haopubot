#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量重置购买提示脚本
用于批量更新 MongoDB 数据库中所有商品的购买提示文本
使用 .env 文件中的最新客服和频道配置
"""

import os
import pymongo
from dotenv import load_dotenv
import logging

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/reset_tips.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# 从环境变量获取配置
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27017/')
MONGO_DB_BOT = os.getenv('MONGO_DB_BOT', 'dingduan')
CUSTOMER_SERVICE = os.getenv('CUSTOMER_SERVICE', '@dingduankeji')
RESTOCK_GROUP = os.getenv('RESTOCK_GROUP', 'https://t.me/dingduankeji')

def reset_purchase_tips():
    """批量重置所有商品的购买提示"""
    try:
        # 连接数据库
        client = pymongo.MongoClient(MONGO_URI)
        db = client[MONGO_DB_BOT]
        ejfl = db['ejfl']
        
        logging.info("🔄 开始批量重置购买提示...")
        logging.info(f"📞 客服：{CUSTOMER_SERVICE}")
        logging.info(f"📣 频道：{RESTOCK_GROUP}")
        
        # 生成新的购买提示文本
        new_text = f'''
<b>✅您的账户已打包完成，请查收！</b>

<b>🔐二级密码:请在json文件中【two2fa】查看！</b>

<b>⚠️注意：请马上检查账户，1小时内出现问题，联系客服处理！</b>
<b>‼️超过售后时间，损失自付，无需多言！</b>

<b>🔹 9号客服  @o9eth  @o7eth</b>
<b>🔹 频道  @idclub9999</b>
<b>🔹 补货通知  @p5540</b>
<b>🔹 账号检测bot  @sfeth666bot </b>
        '''.strip()
        
        # 查询所有商品
        products = list(ejfl.find({}))
        total_count = len(products)
        
        if total_count == 0:
            logging.warning("⚠️ 没有找到任何商品，无需更新")
            return
        
        logging.info(f"📦 找到 {total_count} 个商品，开始批量更新...")
        
        # 批量更新所有商品的购买提示
        result = ejfl.update_many(
            {},  # 空查询条件表示更新所有文档
            {"$set": {"text": new_text}}
        )
        
        updated_count = result.modified_count
        
        logging.info(f"✅ 批量更新完成！")
        logging.info(f"📊 总商品数：{total_count}")
        logging.info(f"🔄 成功更新：{updated_count}")
        logging.info(f"📋 未变化：{total_count - updated_count}")
        
        # 显示更新后的示例
        if updated_count > 0:
            sample_product = ejfl.find_one({})
            if sample_product:
                logging.info(f"📝 更新后的购买提示示例：")
                logging.info(f"商品：{sample_product.get('projectname', '未知')}")
                logging.info(f"提示内容：{sample_product.get('text', '无')[:100]}...")
        
        client.close()
        logging.info("🎉 购买提示重置完成！重启机器人即可生效")
        
    except Exception as e:
        logging.error(f"❌ 重置购买提示失败：{e}")
        raise

def show_current_config():
    """显示当前配置"""
    print("=" * 50)
    print("🤖 购买提示重置工具")
    print("=" * 50)
    print(f"📊 数据库：{MONGO_URI}")
    print(f"🗄️ 数据库名：{MONGO_DB_BOT}")
    print(f"📞 客服：{CUSTOMER_SERVICE}")
    print(f"📣 频道：{RESTOCK_GROUP}")
    print("=" * 50)

def main():
    """主函数"""
    show_current_config()
    
    # 确认操作
    print("\n⚠️ 此操作将批量更新数据库中所有商品的购买提示！")
    print("🔄 更新后的提示将使用 .env 文件中的最新客服和频道信息")
    
    confirm = input("\n是否继续？(y/N): ").strip().lower()
    
    if confirm in ['y', 'yes', '是']:
        try:
            reset_purchase_tips()
            print("\n✅ 操作成功完成！")
            print("💡 请重启机器人以确保所有更改生效")
        except Exception as e:
            print(f"\n❌ 操作失败：{e}")
            return 1
    else:
        print("\n❌ 操作已取消")
        return 0
    
    return 0

if __name__ == "__main__":
    exit(main())
