"""
配置管理
定义配置类，分离机密配置和公开配置
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import os

@dataclass
class TTSSettings:
    """TTS配置"""
    # 机密配置 (仅后端使用)
    app_id: str
    access_token: str
    secret_key: str
    api_base: str
    
    # 对话配置
    available_speakers: List[str]
    max_text_length: int
    max_round_length: int  # 单个对话轮次最大长度
    max_retries: int
    retry_delay: int
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'TTSSettings':
        """从配置字典创建TTS设置"""
        volc_config = config.get('VOLC_TTS', {})
        tts_config = config.get('TTS', {})
        
        return cls(
            # 机密配置
            app_id=volc_config.get('APP_ID', ''),
            access_token=volc_config.get('ACCESS_TOKEN', ''),
            secret_key=volc_config.get('SECRET_KEY', ''),
            api_base=volc_config.get('API_BASE', 'https://open.volcengineapi.com'),
            
            # 对话配置
            available_speakers=tts_config.get('available_speakers', [
                'zh_female_mizai_v2_saturn_bigtts',
                'zh_male_dayi_v2_saturn_bigtts'
            ]),
            max_text_length=tts_config.get('max_text_length', 25000),
            max_round_length=tts_config.get('max_round_length', 250),
            max_retries=tts_config.get('max_retries', 3),
            retry_delay=tts_config.get('retry_delay', 5),
        )

@dataclass
class PublicSettings:
    """公开设置 (可安全暴露给前端)"""
    available_speakers: List[str]
    dialogue_format_example: str
    max_text_length: int
    max_round_length: int  # 单个对话轮次最大长度
    supported_formats: List[str]
    max_concurrent_tasks: int
    task_timeout: int
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'PublicSettings':
        """从配置字典创建公开设置"""
        tts_config = config.get('TTS', {})
        system_config = config.get('SYSTEM', {})
        
        # 筛选包含bigtts的speaker
        all_speakers = tts_config.get('available_speakers', [
            'zh_female_mizai_v2_saturn_bigtts',
            'zh_male_dayi_v2_saturn_bigtts'
        ])
        bigtts_speakers = [speaker for speaker in all_speakers if 'bigtts' in speaker]
        
        return cls(
            available_speakers=bigtts_speakers,
            dialogue_format_example="婷婷（活泼感性）：对话内容\n小西（逻辑严谨）：对话内容",
            max_text_length=tts_config.get('max_text_length', 25000),
            max_round_length=tts_config.get('max_round_length', 250),
            supported_formats=tts_config.get('supported_formats', ['.txt']),
            max_concurrent_tasks=system_config.get('max_concurrent_tasks', 5),
            task_timeout=system_config.get('task_timeout', 300),
        )
