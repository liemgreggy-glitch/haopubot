import hashlib
import urllib.parse
import os
import qrcode
from PIL import Image, ImageDraw, ImageFont
import io

def verify_easypay_sign(data: dict, key: str = None) -> bool:
    """
    验证易支付签名

    参数:
        data: dict，回调收到的参数字典
        key: str，可选，不传时自动从环境变量读取 EASYPAY_KEY

    返回:
        bool，签名是否有效
    """
    if key is None:
        key = os.getenv('EASYPAY_KEY')  # 自动从 .env 中读取密钥

    if not key:
        return False

    original_sign = data.get('sign')
    if not original_sign:
        return False

    sign_type = data.get('sign_type', 'MD5').upper()
    if sign_type != 'MD5':
        return False

    # 排除 sign 和 sign_type 字段
    params = {k: v for k, v in data.items() if k not in ['sign', 'sign_type'] and v != ''}

    # 排序并拼接参数
    sign_str = '&'.join(f"{k}={params[k]}" for k in sorted(params))
    sign_str += key

    # 生成 MD5 签名
    md5 = hashlib.md5()
    md5.update(sign_str.encode('utf-8'))
    calculated_sign = md5.hexdigest()

    # 比较签名是否一致（不区分大小写）
    return calculated_sign.lower() == original_sign.lower()


def create_easypay_url(pid: str, key: str, gateway_url: str,
                       out_trade_no: str, name: str, money: float,
                       notify_url: str, return_url: str, payment_type: str) -> str:
    """
    构造易支付下单跳转链接
    """
    params = {
        "pid": pid,
        "type": payment_type,
        "out_trade_no": out_trade_no,
        "notify_url": notify_url,
        "return_url": return_url,
        "name": name,
        "money": str(money)
    }

    sign_str = '&'.join(f"{k}={params[k]}" for k in sorted(params))
    sign = hashlib.md5((sign_str + key).encode('utf-8')).hexdigest()
    params["sign"] = sign
    params["sign_type"] = "MD5"

    return f"{gateway_url}?{urllib.parse.urlencode(params)}"


def generate_payment_qrcode(payment_url: str, payment_type: str, amount: float, 
                           order_no: str, save_path: str = None) -> str:
    """
    生成支付二维码图片
    
    参数:
        payment_url: str，支付链接
        payment_type: str，支付类型 ('wechat' 或 'alipay')
        amount: float，支付金额
        order_no: str，订单号
        save_path: str，可选，保存路径，不传则使用默认路径
    
    返回:
        str，二维码图片文件路径
    """
    # 创建二维码
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payment_url)
    qr.make(fit=True)

    # 生成二维码图片
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # 创建带标题的图片
    img_width = 400
    img_height = 500
    
    # 创建白色背景图片
    img = Image.new('RGB', (img_width, img_height), 'white')
    draw = ImageDraw.Draw(img)
    
    # 调整二维码大小
    qr_img = qr_img.resize((300, 300), Image.LANCZOS)
    
    # 将二维码粘贴到中心位置
    qr_x = (img_width - 300) // 2
    qr_y = 80
    img.paste(qr_img, (qr_x, qr_y))
    
    try:
        # 尝试使用系统字体
        if os.name == 'nt':  # Windows
            font_title = ImageFont.truetype('msyh.ttc', 24)  # 微软雅黑
            font_info = ImageFont.truetype('msyh.ttc', 16)
        else:  # Linux/Mac
            font_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 24)
            font_info = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
    except:
        # 如果系统字体不可用，使用默认字体
        font_title = ImageFont.load_default()
        font_info = ImageFont.load_default()
    
    # 支付方式标题
    payment_names = {
        'wechat': '微信支付',
        'alipay': '支付宝支付',
        'wxpay': '微信支付'
    }
    title = payment_names.get(payment_type, '扫码支付')
    
    # 计算文字位置并绘制
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (img_width - title_width) // 2
    draw.text((title_x, 20), title, fill='black', font=font_title)
    
    # 金额信息
    amount_text = f"支付金额: ¥{amount}"
    amount_bbox = draw.textbbox((0, 0), amount_text, font=font_info)
    amount_width = amount_bbox[2] - amount_bbox[0]
    amount_x = (img_width - amount_width) // 2
    draw.text((amount_x, 400), amount_text, fill='black', font=font_info)
    
    # 订单号信息
    order_text = f"订单号: {order_no}"
    order_bbox = draw.textbbox((0, 0), order_text, font=font_info)
    order_width = order_bbox[2] - order_bbox[0]
    order_x = (img_width - order_width) // 2
    draw.text((order_x, 430), order_text, fill='black', font=font_info)
    
    # 提示信息
    tip_text = "请使用对应APP扫码支付"
    tip_bbox = draw.textbbox((0, 0), tip_text, font=font_info)
    tip_width = tip_bbox[2] - tip_bbox[0]
    tip_x = (img_width - tip_width) // 2
    draw.text((tip_x, 460), tip_text, fill='gray', font=font_info)
    
    # 确定保存路径
    if save_path is None:
        # 创建 qr_codes 目录（如果不存在）
        qr_dir = "qr_codes"
        if not os.path.exists(qr_dir):
            os.makedirs(qr_dir)
        save_path = os.path.join(qr_dir, f"{payment_type}_{order_no}.png")
    
    # 保存图片
    img.save(save_path)
    return save_path


def create_payment_with_qrcode(pid: str, key: str, gateway_url: str,
                              out_trade_no: str, name: str, money: float,
                              notify_url: str, return_url: str, payment_type: str) -> dict:
    """
    创建支付链接和二维码
    
    返回:
        dict，包含 'url' 和 'qrcode_path' 的字典
    """
    # 生成支付链接
    payment_url = create_easypay_url(
        pid, key, gateway_url, out_trade_no, name, money,
        notify_url, return_url, payment_type
    )
    
    # 生成二维码
    qrcode_path = generate_payment_qrcode(
        payment_url, payment_type, money, out_trade_no
    )
    
    return {
        'url': payment_url,
        'qrcode_path': qrcode_path
    }
