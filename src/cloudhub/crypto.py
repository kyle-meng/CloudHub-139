import base64
import json
import os
import gzip
import io
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad


class YunCrypto:
    def __init__(self, key: bytes = b"PVGDwmcvfs1uV3d1"):
        self.key = key
        self.block_size = 16

    def encrypt(self, data_obj: dict) -> str:
        """
        将字典对象加密为 Base64 字符串。
        使用随机 IV，AES-CBC 模式，PKCS7 填充。
        """
        try:
            iv = os.urandom(self.block_size)
            cipher = AES.new(self.key, AES.MODE_CBC, iv)
            # 使用紧凑型 JSON 序列化 (无空格)
            json_str = json.dumps(data_obj, separators=(',', ':'), ensure_ascii=False)
            ct_bytes = cipher.encrypt(pad(json_str.encode('utf-8'), self.block_size))
            # 拼接 IV + 密文后进行 Base64 编码
            return base64.b64encode(iv + ct_bytes).decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"Encryption failed: {e}")

    def decrypt(self, b64_data: str) -> str:
        """
        解密 Base64 字符串。
        支持处理 Gzip 压缩及移除 PKCS7 填充。
        """
        try:
            # 移除数据中的空白字符
            b64_data = "".join(b64_data.split())
            raw_data = base64.b64decode(b64_data)
            
            if len(raw_data) < self.block_size:
                raise ValueError("Data too short to contain IV")

            iv = raw_data[:self.block_size]
            ct = raw_data[self.block_size:]
            cipher = AES.new(self.key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(ct)
            
            # 1. 尝试处理 Gzip (魔数 1f 8b)
            if decrypted.startswith(b'\x1f\x8b'):
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(decrypted)) as f:
                        return f.read().decode('utf-8')
                except Exception as ge:
                    # 如果 Gzip 解压失败，回退到普通字符串处理
                    pass
            
            # 2. 移除 PKCS7 填充并解码
            try:
                return unpad(decrypted, self.block_size).decode('utf-8')
            except Exception:
                # 兼容处理非标准填充
                return decrypted.decode('utf-8', errors='ignore').strip()
                
        except Exception as e:
            raise RuntimeError(f"Decryption failed: {e}")
