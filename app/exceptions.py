"""TTS相关异常定义"""

class TtsError(Exception):
    """TTS基础异常"""
    pass

class ConcurrencyQuotaExceeded(TtsError):
    """并发配额超限异常（错误码45000292）"""
    def __init__(self, message: str, error_code: int = 45000292):
        self.error_code = error_code
        super().__init__(f"[{error_code}] {message}")

class TtsServerError(TtsError):
    """TTS服务器错误"""
    def __init__(self, error_code: int, error_data: dict):
        self.error_code = error_code
        self.error_data = error_data
        super().__init__(f"[{error_code}] {error_data}")

