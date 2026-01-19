import json
import time
import itertools
import logging
import os
import requests
from dotenv import load_dotenv
from tronpy.providers import HTTPProvider
from tronpy import Tron
import tronpy.exceptions
import pika
from pika import exceptions

# 加载环境变量
load_dotenv()

# ✅ 日志设置优化
def init_logging():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "zf.log")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler()  # 同时输出到控制台
        ]
    )
    logging.info("🟢 zf_heijiang 启动成功")

init_logging()

# ===== Tron APIKey 轮换机制 =====
api_keys = os.getenv("TRON_API_KEYS", "").split(",")
api_key_cycle = itertools.cycle(api_keys)

def get_tron_client():
    current_key = next(api_key_cycle)
    logging.info(f"🔁 使用 Tron API Key: {current_key[:6]}...")
    return Tron(HTTPProvider(api_key=current_key))

# ===== RabbitMQ 连接 =====
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "telegram")

credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
connection = pika.BlockingConnection(pika.ConnectionParameters(
    host=RABBITMQ_HOST,
    port=RABBITMQ_PORT,
    virtual_host=RABBITMQ_VHOST,
    credentials=credentials
))
channel = connection.channel()
channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

# ===== 推送区块数据到 MQ =====
def send_to_rabbitmq(block_data, block):
    try:
        message = json.dumps({"block_list": block_data})
        channel.basic_publish(
            exchange='',
            routing_key=RABBITMQ_QUEUE,
            body=message.encode()
        )
        logging.info(f"✅ 推送区块 {block} 到 MQ 成功")
    except pika.exceptions.AMQPError as e:
        logging.error(f"❌ MQ 推送失败：{e}")

# ===== 获取区块并推送到 MQ =====
def get_data(block) -> None:
    retry = 0
    while retry < 5:
        try:
            client = get_tron_client()
            block_data = client.get_block(block)

            if 'transactions' in block_data and block_data['transactions']:
                send_to_rabbitmq(block_data, block)
            else:
                logging.info(f"⏩ 区块 {block} 无交易，跳过")
            return

        except tronpy.exceptions.BlockNotFound:
            logging.warning(f"⏳ 区块未生成：{block}，等待中...")
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            logging.warning(f"🌐 网络错误：{e}，尝试切换 Key 重试")
            retry += 1
            time.sleep(2)
        except Exception as e:
            logging.exception(f"❌ 区块 {block} 拉取异常")
            retry += 1
            time.sleep(2)

# ===== 主循环 =====
if __name__ == '__main__':
    client = get_tron_client()
    block = client.get_latest_block()['block_header']['raw_data']['number'] - 1

    while True:
        get_data(block)
        block += 1
        time.sleep(1)
