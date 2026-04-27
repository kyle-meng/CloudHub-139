import requests
import json
from .crypto import YunCrypto

class YunClient:
    def __init__(self, auth_token: str, account: str):
        self.url = "https://share-kd-njs.yun.139.com/yun-share/richlifeApp/devapp/IOutLink/getOutLinkInfoV6"
        self.auth_token = auth_token
        self.account = account
        self.crypto = YunCrypto()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Deviceinfo': '||9|12.27.0|firefox|140.0|12b780037221ab547c682223327dc9cd||linux unknow|1920X526|zh-CN|||',
            'hcy-cool-flag': '1',
            'CMS-DEVICE': 'default',
            'x-m4c-caller': 'PC',
            'x-yun-api-version': 'v1',
            'Authorization': self.auth_token,
            'Origin': 'https://yun.139.com',
            'Referer': 'https://yun.139.com/'
        }

    def set_signatures(self, mcloud_sign: str, mcloud_skey: str):
        """更新额外的校验签名参数"""
        self.headers.update({
            'mcloud-sign': mcloud_sign,
            'mcloud-skey': mcloud_skey
        })

    def get_out_link_info(self, link_id: str, p_ca_id: str = "root"):
        """
        获取分享链接内的文件/文件夹信息。
        """
        raw_payload = {
            "getOutLinkInfoReq": {
                "account": self.account,
                "linkID": link_id,
                "passwd": "",
                "caSrt": 0,
                "coSrt": 0,
                "srtDr": 1,
                "bNum": 1,
                "pCaID": p_ca_id,
                "eNum": 200
            },
            "commonAccountInfo": {
                "account": self.account,
                "accountType": 1
            }
        }

        try:
            encrypted_body = self.crypto.encrypt(raw_payload)
            print(f"[*] 发送请求: Link[{link_id}] ParentID[{p_ca_id}]")
            res = requests.post(self.url, data=encrypted_body, headers=self.headers, timeout=15)
            res.raise_for_status()

            decrypted_text = self.crypto.decrypt(res.text)
            response_json = json.loads(decrypted_text)

            if response_json.get("resultCode") == "0":
                return response_json.get("data", {})
            else:
                print(f"[!] 业务错误: {response_json.get('resultCode')} - {response_json.get('desc')}")
                return None
        except Exception as e:
            print(f"[x] 请求失败: {e}")
            return None

    def get_content_info(self, content_id: str, link_id: str):
        """
        获取内容的详细播放信息 (getContentInfoFromOutLink)。
        """
        info_url = "https://share-kd-njs.yun.139.com/yun-share/richlifeApp/devapp/IOutLink/getContentInfoFromOutLink"
        payload = {
            "getContentInfoFromOutLinkReq": {
                "contentId": content_id,
                "linkID": link_id,
                "account": self.account
            },
            "commonAccountInfo": {
                "account": self.account,
                "accountType": 1
            }
        }
        
        try:
            print(f"[*] 获取播放信息: Content[{content_id}]")
            res = requests.post(info_url, json=payload, headers=self.headers, timeout=15)
            
            data = None
            if res.status_code == 200 and res.text.strip():
                try:
                    data = res.json()
                    if isinstance(data, str):
                        data = json.loads(data)
                except Exception:
                    data = None

            if data is None or data.get("resultCode") != "0":
                encrypted_payload = self.crypto.encrypt(payload)
                res = requests.post(info_url, data=encrypted_payload, headers=self.headers, timeout=15)
                
                if res.status_code == 200 and res.text.strip():
                    try:
                        decrypted_text = self.crypto.decrypt(res.text)
                        data = json.loads(decrypted_text)
                        if isinstance(data, str):
                            data = json.loads(data)
                    except Exception as e:
                        print(f"[!] 加密解密失败: {e}")
                        return None
            
            if data and data.get("resultCode") == "0":
                return data.get("data", {})
            else:
                desc = data.get("desc") if data else "未知错误"
                print(f"[!] 获取失败: {desc}")
                return None
        except Exception as e:
            print(f"[x] 请求异常: {e}")
            return None

    def get_playlist_m3u8(self, content_id: str, link_id: str, resolution="1920x1080"):
        """
        获取并处理 M3U8 播放列表，返回补全后的绝对链接内容。
        """
        import urllib.parse
        import os
        
        # 1. 获取基础播放信息 (含 presentURL)
        info = self.get_content_info(content_id, link_id)
        if not info: return None
        
        master_url = info.get('contentInfo', {}).get('presentURL')
        if not master_url:
            print("[!] 未找到播放地址 (presentURL)")
            return None
        
        # 使用“干净”的 Header 请求静态资源，避免 Authorization 干扰签名校验
        resource_headers = {
            'User-Agent': self.headers['User-Agent'],
            'Accept': '*/*',
            'Origin': self.headers['Origin'],
            'Referer': self.headers['Referer'],
            'Connection': 'keep-alive'
        }
        
        # 2. 获取 Master M3U8
        res_master = requests.get(master_url, headers=resource_headers, timeout=10)
        res_master.raise_for_status()
        master_content = res_master.text
        
        # 3. 定位对应分辨率的流路径
        media_rel_path = ""
        lines = master_content.split('\n')
        for i, line in enumerate(lines):
            if f"RESOLUTION={resolution}" in line:
                media_rel_path = lines[i+1].strip()
                break
        
        if not media_rel_path:
            for i, line in enumerate(lines):
                if "RESOLUTION=" in line:
                    media_rel_path = lines[i+1].strip()
                    break
        
        if not media_rel_path:
            print("[!] 未能在 Master 列表中找到对应流路径")
            return None
        
        # 4. 获取 Sub-playlist 内容并保存原始文件
        media_url = urllib.parse.urljoin(master_url, media_rel_path)
        res_media = requests.get(media_url, headers=resource_headers, timeout=10)
        res_media.raise_for_status()
        media_content = res_media.text
        
        with open("origin_media.m3u8", "w", encoding="utf-8") as f:
            f.write(media_content)

        # 5. 补全 TS 链接
        final_lines = []
        for line in media_content.split('\n'):
            clean_line = line.strip()
            if clean_line and not clean_line.startswith("#"):
                # 严格按照 urljoin 逻辑补全绝对路径
                full_ts_url = urllib.parse.urljoin(media_url, clean_line)
                final_lines.append(full_ts_url)
            else:
                final_lines.append(line)
                
        return "\n".join(final_lines)
