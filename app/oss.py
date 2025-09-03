import os
import oss2
from typing import Optional


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
        self.bucket.put_object(object_key, data, headers=headers)
        return self.public_url(object_key)

    def upload_file(self, object_key: str, file_path: str, content_type: Optional[str] = None) -> str:
        headers = {}
        if content_type:
            headers['Content-Type'] = content_type
        self.bucket.put_object_from_file(object_key, file_path, headers=headers)
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

    @staticmethod
    def _strip_scheme(endpoint: str) -> str:
        return endpoint.replace('https://', '').replace('http://', '')
