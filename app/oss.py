import os
import time
import oss2
from typing import Optional, Callable


class OssClient:
    def __init__(self, endpoint: str, bucket: str, access_key_id: str, access_key_secret: str):
        auth = oss2.Auth(access_key_id, access_key_secret)
        self.bucket_name = bucket
        self.bucket = oss2.Bucket(auth, endpoint, bucket)
        self.endpoint = endpoint

    def upload_bytes(self, object_key: str, data: bytes, content_type: Optional[str] = None) -> str:
        headers = {}
        if content_type:
            headers['Content-Type'] = content_type
        self._with_retry(lambda: self.bucket.put_object(object_key, data, headers=headers))
        return self.public_url(object_key)

    def upload_file(self, object_key: str, file_path: str, content_type: Optional[str] = None) -> str:
        headers = {}
        if content_type:
            headers['Content-Type'] = content_type
        self._with_retry(lambda: self.bucket.put_object_from_file(object_key, file_path, headers=headers))
        return self.public_url(object_key)

    def public_url(self, object_key: str) -> str:
        # Bucket 配置为公开读时，直接拼接公网URL
        # 也可使用 bucket.sign_url 生成临时签名，但本项目要求公开读无需签名
        return f"https://{self.bucket_name}.{self._strip_scheme(self.endpoint)}/{object_key}"

    def object_exists(self, object_key: str) -> bool:
        """检查对象是否存在"""
        try:
            self.bucket.head_object(object_key)
            return True
        except oss2.exceptions.NoSuchKey:
            return False
        except Exception:
            return False

    def get_object_size(self, object_key: str) -> int:
        """获取OSS对象的文件大小
        
        Args:
            object_key: OSS对象键
            
        Returns:
            文件大小（字节）
            
        Raises:
            Exception: 如果文件不存在或获取失败
        """
        try:
            # 使用 head_object 获取文件元信息（不下载文件内容）
            obj_meta = self.bucket.head_object(object_key)
            file_size = int(obj_meta.headers.get('Content-Length', 0))
            return file_size
        except Exception as e:
            raise Exception(f"获取文件大小失败: {object_key}, {e}")

    @staticmethod
    def _strip_scheme(endpoint: str) -> str:
        return endpoint.replace('https://', '').replace('http://', '')

    # ========== 辅助函数 ==========
    @staticmethod
    def sanitize_path_segment(name: str) -> str:
        """将标题/文件夹名转成安全的路径段：去掉危险字符，空白改下划线。"""
        if not name:
            return "untitled"
        safe = name.strip()
        # 替换路径分隔与控制字符
        for ch in ['\\\n', '\\r', '\\t', '/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            safe = safe.replace(ch, '_')
        # 连续空白压缩为一个下划线
        safe = '_'.join(safe.split())
        # 限制长度，避免超长Key
        return safe[:128] if len(safe) > 128 else safe

    def _with_retry(self, fn: Callable[[], None], *, retries: int = 3, base_delay: float = 0.5) -> None:
        """对 OSS 写操作做简单重试，处理瞬时 5xx/限流。"""
        attempt = 0
        while True:
            try:
                fn()
                return
            except Exception as e:
                attempt += 1
                if attempt > retries:
                    raise
                time.sleep(base_delay * (2 ** (attempt - 1)))
