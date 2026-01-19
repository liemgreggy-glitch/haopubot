# 读取文件
with open('agent_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 查找最后一个完整的 } 位置，这应该是 process_purchase 方法的返回字典结束
lines = content.split('\n')

# 找到 AgentBotCore 类和合适的插入位置
insert_pos = -1
agentbotcore_found = False

for i, line in enumerate(lines):
    if 'class AgentBotCore' in line:
        agentbotcore_found = True
        continue
    
    # 在 AgentBotCore 类中，找到一个合适的插入位置
    if agentbotcore_found:
        # 查找 process_purchase 方法返回后的位置
        if line.strip() == '}' and i > 0 and 'return True' in lines[i-5:i]:
            insert_pos = i + 2  # 在 } 后面空一行插入
            break
        # 或者找到下一个类开始的位置
        elif line.startswith('class ') and 'AgentBotCore' not in line:
            insert_pos = i
            break

if insert_pos == -1:
    # 如果没找到，在文件末尾插入
    insert_pos = len(lines)

print(f"将在第 {insert_pos + 1} 行插入方法")

# 要插入的方法
new_method = '''    def send_item_file_to_user(self, user_id, item, product_name):
        """发送单个商品的文件给用户"""
        logger.info(f"🔔 开始发送文件流程: user_id={user_id}, product_name={product_name}")
        logger.info(f"🔍 商品数据: {item}")
        
        try:
            import os
            from telegram import Bot
            
            # 直接使用华南代理的token
            bot_token = "8585365683:AAFf2IfDjVsqlpDHrEJKcEvO3jzlxF56JzU"
            logger.info(f"🔍 使用代理机器人token")
            
            # 创建机器人实例
            bot = Bot(token=bot_token)
            
            # 获取商品信息
            item_projectname = item.get('projectname', '')
            item_leixing = item.get('leixing', '')
            item_nowuid = item.get('nowuid', '')
            
            logger.info(f"🔍 商品详细信息:")
            logger.info(f"   projectname: {item_projectname}")
            logger.info(f"   leixing: {item_leixing}")
            logger.info(f"   nowuid: {item_nowuid}")
            
            # 根据商品类型和nowuid确定文件路径
            if item_leixing == '协议号':
                product_dir = f'/www/9haobot/9hao/协议号/{item_nowuid}'
            else:
                product_dir = f'/www/9haobot/9hao/{item_leixing}/{item_nowuid}'
            
            logger.info(f"🔍 计算的文件目录: {product_dir}")
            
            # 检查目录是否存在
            if not os.path.exists(product_dir):
                logger.warning(f"⚠️ 商品目录不存在: {product_dir}")
                return False
            
            # 查找目录中的文件
            try:
                files_in_dir = os.listdir(product_dir)
                logger.info(f"🔍 目录 {product_dir} 中的文件: {files_in_dir}")
                
                if not files_in_dir:
                    logger.warning(f"⚠️ 目录为空: {product_dir}")
                    return False
                
                # 优先查找压缩文件和文本文件
                priority_extensions = ['.zip', '.rar', '.7z', '.txt']
                found_files = []
                
                for ext in priority_extensions:
                    for file in files_in_dir:
                        if file.lower().endswith(ext):
                            found_files.append(os.path.join(product_dir, file))
                
                # 如果没找到优先文件，添加其他文件
                if not found_files:
                    for file in files_in_dir:
                        file_path = os.path.join(product_dir, file)
                        if os.path.isfile(file_path):
                            found_files.append(file_path)
                
                logger.info(f"🔍 找到的文件列表: {found_files}")
                
                files_sent = 0
                
                # 发送所有找到的文件
                for file_path in found_files:
                    try:
                        file_size = os.path.getsize(file_path)
                        file_name = os.path.basename(file_path)
                        
                        logger.info(f"📁 准备发送文件: {file_name} (大小: {file_size} bytes)")
                        
                        # 检查文件大小（Telegram限制50MB）
                        if file_size > 50 * 1024 * 1024:
                            logger.warning(f"⚠️ 文件太大，跳过: {file_name}")
                            continue
                        
                        # 发送文件
                        with open(file_path, 'rb') as file:
                            result = bot.send_document(
                                chat_id=user_id,
                                document=file,
                                caption=f"📁 <b>{product_name}</b>\\n\\n📦 商品文件: {file_name}\\n💼 商品编号: {item_projectname}\\n🔔 请妥善保存文件内容",
                                parse_mode='HTML'
                            )
                        
                        logger.info(f"✅ 成功发送文件: {file_name} (message_id: {result.message_id})")
                        files_sent += 1
                        
                    except Exception as send_error:
                        logger.error(f"❌ 发送文件失败 {file_name}: {send_error}")
                        continue
                
                if files_sent > 0:
                    logger.info(f"✅ 总共发送了 {files_sent} 个文件给用户 {user_id}")
                    return True
                else:
                    logger.warning(f"⚠️ 没有成功发送任何文件")
                    return False
                    
            except Exception as list_error:
                logger.error(f"❌ 读取目录失败: {list_error}")
                return False
            
        except Exception as e:
            logger.error(f"❌ 发送文件处理失败: {e}")
            import traceback
            traceback.print_exc()
            return False
'''

# 插入新方法
lines.insert(insert_pos, '')  # 空行
lines.insert(insert_pos + 1, new_method)

# 写回文件
with open('agent_bot.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print("✅ 修复完成")
