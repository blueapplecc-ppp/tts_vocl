"""
日志配置模块
提供结构化日志记录，支持脱敏和滚动落盘
"""
import logging
import logging.handlers
import json
import os
import re
import threading
from datetime import datetime
from typing import Any, Dict, Optional


class SensitiveDataFilter(logging.Filter):
    """敏感数据过滤器，用于脱敏日志"""
    
    SENSITIVE_PATTERNS = [
        (r'access_token["\']?\s*[:=]\s*["\']?([^"\',\s}]+)', 'access_token="***"'),
        (r'app_id["\']?\s*[:=]\s*["\']?([^"\',\s}]+)', 'app_id="***"'),
        (r'secret["\']?\s*[:=]\s*["\']?([^"\',\s}]+)', 'secret="***"'),
        (r'password["\']?\s*[:=]\s*["\']?([^"\',\s}]+)', 'password="***"'),
        (r'key["\']?\s*[:=]\s*["\']?([^"\',\s}]+)', 'key="***"'),
    ]
    
    def filter(self, record):
        """过滤敏感信息"""
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            for pattern, replacement in self.SENSITIVE_PATTERNS:
                record.msg = re.sub(pattern, replacement, record.msg)
        return True


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器"""
    
    def format(self, record):
        """格式化日志记录为JSON结构"""
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # 添加异常信息
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # 添加额外字段
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
        
        return json.dumps(log_entry, ensure_ascii=False, separators=(',', ':'))


def setup_logging(log_dir: str = "logs", log_level: str = "INFO") -> None:
    """设置日志系统"""
    
    # 确保日志目录存在
    os.makedirs(log_dir, exist_ok=True)
    
    # 创建根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(console_handler)
    
    # 文件处理器（滚动日志）
    log_file = os.path.join(log_dir, "tts_vocl.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_handler.setFormatter(StructuredFormatter())
    file_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(file_handler)
    
    # 错误日志文件处理器
    error_log_file = os.path.join(log_dir, "tts_vocl_error.log")
    error_handler = logging.handlers.RotatingFileHandler(
        error_log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(StructuredFormatter())
    error_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(error_handler)


def get_logger(name: str) -> logging.Logger:
    """获取日志器"""
    return logging.getLogger(name)


def log_with_context(logger: logging.Logger, level: int, message: str, 
                    **extra_fields) -> None:
    """记录带上下文的日志"""
    extra_fields['extra_fields'] = extra_fields
    logger.log(level, message, extra=extra_fields)


# 内存日志缓冲器（用于调试接口）
class MemoryLogBuffer:
    """内存日志缓冲器，用于存储最近的日志记录"""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.logs = []
        self.lock = threading.RLock()
    
    def add_log(self, log_entry: Dict[str, Any]) -> None:
        """添加日志记录"""
        with self.lock:
            self.logs.append(log_entry)
            if len(self.logs) > self.max_size:
                self.logs.pop(0)
    
    def get_logs(self, text_id: Optional[int] = None, 
                level: Optional[str] = None) -> list:
        """获取日志记录"""
        with self.lock:
            filtered_logs = self.logs.copy()
            
            if text_id is not None:
                filtered_logs = [
                    log for log in filtered_logs 
                    if log.get('extra_fields', {}).get('text_id') == text_id
                ]
            
            if level is not None:
                filtered_logs = [
                    log for log in filtered_logs 
                    if log.get('level') == level.upper()
                ]
            
            return filtered_logs[-100:]  # 返回最近100条
    
    def clear(self) -> None:
        """清空日志缓冲"""
        with self.lock:
            self.logs.clear()


# 全局内存日志缓冲器
memory_log_buffer = MemoryLogBuffer()


class MemoryLogHandler(logging.Handler):
    """内存日志处理器，将日志同时写入内存缓冲"""
    
    def emit(self, record):
        """发送日志记录到内存缓冲"""
        try:
            log_entry = {
                'timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
                'module': record.module,
                'function': record.funcName,
                'line': record.lineno,
            }
            
            if record.exc_info:
                log_entry['exception'] = self.formatException(record.exc_info)
            
            if hasattr(record, 'extra_fields'):
                log_entry['extra_fields'] = record.extra_fields
            
            memory_log_buffer.add_log(log_entry)
        except Exception:
            pass  # 避免日志记录本身出错


def add_memory_handler(logger: logging.Logger) -> None:
    """为日志器添加内存处理器"""
    memory_handler = MemoryLogHandler()
    memory_handler.setFormatter(StructuredFormatter())
    logger.addHandler(memory_handler)


# threading已在上方导入
