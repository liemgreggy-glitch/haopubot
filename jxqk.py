import json
import requests
import time
import logging
import os
from pika.exceptions import AMQPError, ChannelClosedByBroker
import pika
import tronpy.exceptions
from tronpy.providers import HTTPProvider
from tronpy import Tron
import pymongo
from dotenv import load_dotenv
from itertools import cycle

# ====== 载入 .env 配置 ======
load_dotenv()

# ✅ 日志设置优化
def init_logging():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "jxqk.log")
    
    # 创建 logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 清除现有的 handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 文件日志 handler
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    # 终端日志 handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    
    logging.info("🟢 jxqk 监听服务启动成功")

init_logging()

# ====== MongoDB 连接 ======
teleclient = pymongo.MongoClient(os.getenv("MONGO_URI"))
mydb = teleclient[os.getenv("MONGO_DB_QUKUAI")]
qukuai = mydb['qukuai']

mydb1 = teleclient[os.getenv("MONGO_DB_XCHP")]
shangtext = mydb1['shangtext']

# ====== RabbitMQ 连接 ======
credentials = pika.PlainCredentials(
    os.getenv("RABBITMQ_USER"),
    os.getenv("RABBITMQ_PASS")
)
connection = pika.BlockingConnection(pika.ConnectionParameters(
    host=os.getenv("RABBITMQ_HOST"),
    port=int(os.getenv("RABBITMQ_PORT")),
    virtual_host=os.getenv("RABBITMQ_VHOST"),
    credentials=credentials
))
channel = connection.channel()

# ====== Tron API 客户端（支持轮换） ======
TRON_API_KEYS = os.getenv("TRON_API_KEYS", "").split(",")
api_key_cycle = cycle(TRON_API_KEYS)
client = Tron(HTTPProvider(api_key=next(api_key_cycle)))

# ====== 查地址 ======
def search_address():
    record = shangtext.find_one({'projectname': '充值地址'})
    if not record or 'text' not in record:
        logging.warning("⚠️ 未找到充值地址字段，返回空地址列表")
        return []
    return [record['text']]

# ====== MQ 数据发送 ======
def send_message_to_queue(message_data):
    try:
        message_json = json.dumps(message_data)
        channel.basic_publish(exchange='', routing_key=os.getenv("RABBITMQ_OUTPUT_QUEUE", "tronweb_data"), body=message_json)
        logging.info(f"📤 成功发送数据到 RabbitMQ: {message_data}")
    except (AMQPError, ChannelClosedByBroker) as e:
        logging.error(f"❌ 发送数据到 RabbitMQ 失败: {e}")

# ====== 主回调函数 ======
def callback(ch, method, properties, body) -> None:
    try:
        ch.basic_ack(delivery_tag=method.delivery_tag)
        text = body.decode('utf-8')
        block_list = json.loads(text)['block_list']
        transactions = block_list['transactions']
        number = block_list['block_header']['raw_data']['number']
        address_list = search_address()
        logging.info(f"📦 收到区块数据：Block #{number}，交易数量：{len(transactions)}")

        for trx in transactions:
            if trx["ret"][0]["contractRet"] == "SUCCESS":
                contract = trx["raw_data"]["contract"][0]
                contract_type = contract["type"]
                value = contract["parameter"]["value"]
                txid = trx['txID']

                if contract_type == "TriggerSmartContract":
                    contract_address = client.to_base58check_address(value["contract_address"])
                    data = value['data']
                    # 🔒 Security: Verify this is genuine USDT contract (TRC20)
                    if contract_address == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                        # 🔒 Security: Verify transfer method signature
                        if data[:8] == "a9059cbb":
                            from_address = client.to_base58check_address(value["owner_address"])
                            to_address = client.to_base58check_address('41' + (data[8:72])[-40:])
                            quant = int(data[-64:], 16)
                            
                            # 🔒 Security Check: Skip zero-value transactions
                            if quant == 0:
                                continue
                            
                            # 🔒 Security Check: Validate addresses are not empty
                            if not from_address or not to_address:
                                logging.warning(f"⚠️ 交易地址异常: txid={txid}, from={from_address}, to={to_address}")
                                continue
                            
                            timestamp = trx.get("raw_data", {}).get("timestamp", int(round(time.time() * 1000)))
                            
                            # 🔒 Security Check: Validate timestamp
                            if timestamp <= 0:
                                logging.warning(f"⚠️ 交易时间戳异常: txid={txid}, timestamp={timestamp}")
                                continue

                            message_data = {
                                "txid": txid,
                                "type": "USDT",
                                "from_address": from_address,
                                "to_address": to_address,
                                "quant": quant,
                                "time": timestamp,
                                "number": number,
                                "state": 0,
                                # 🔒 Security: Add contract verification flag
                                "contract_verified": True,
                                "contract_address": contract_address
                            }

                            if message_data['to_address'] in address_list:
                                # 🔒 Security: Check for duplicate TXID before inserting
                                existing = qukuai.find_one({'txid': txid})
                                if existing:
                                    logging.warning(f"⚠️ 重复交易TXID，跳过: {txid}")
                                    continue
                                
                                qukuai.insert_one(message_data)
                                logging.info(f"✅ 成功入库 USDT 交易: txid={txid}, amount={quant/1000000:.6f}, from={from_address[:10]}..., to={to_address[:10]}...")

    except (AMQPError, ChannelClosedByBroker) as e:
        logging.error(f"❌ MQ 接收失败: {e}")
    except Exception as e:
        logging.exception(f"❌ 扫描区块时发生异常: {e}")

# ====== 启动监听 ======
if __name__ == '__main__':
    try:
        channel.basic_consume(os.getenv("RABBITMQ_INPUT_QUEUE", "telegram"), callback)
        logging.info("📡 开始监听 RabbitMQ 队列")
        channel.start_consuming()
    except KeyboardInterrupt:
        logging.info("🛑 手动中断 jxqk 消费进程")
    except Exception as e:
        logging.exception(f"❌ 主线程异常: {e}")