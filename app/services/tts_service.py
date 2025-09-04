"""
TTS服务层
提供文本转语音的业务逻辑抽象
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import asyncio
import logging

logger = logging.getLogger(__name__)

class TTSServiceInterface(ABC):
    """TTS服务抽象接口"""
    
    @abstractmethod
    async def synthesize_text(self, text: str, voice: str = "female", **kwargs) -> bytes:
        """合成文本为音频"""
        pass
    
    @abstractmethod
    def get_available_voices(self) -> List[str]:
        """获取可用音色列表"""
        pass

class TTSService(TTSServiceInterface):
    """TTS服务实现"""
    
    def __init__(self, tts_client, config: Dict[str, Any]):
        self.tts_client = tts_client
        self.config = config
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 5)
        # 对话模式：筛选包含bigtts的speaker
        self.available_speakers = config.get('available_speakers', [
            'zh_female_mizai_v2_saturn_bigtts',
            'zh_male_dayi_v2_saturn_bigtts'
        ])
    
    async def synthesize_text(self, text: str, **kwargs) -> bytes:
        """合成对话文本为音频，包含重试机制"""
        text_id = kwargs.get('text_id')
        ctx = f"[text_id={text_id}] " if text_id is not None else ""
        logger.info(f"{ctx}=== TTS服务开始合成 ===")
        logger.info(f"{ctx}文本长度: {len(text)}")
        logger.info(f"{ctx}文本预览: {text[:200]}...")
        logger.info(f"{ctx}额外参数: { {k:v for k,v in kwargs.items() if k!='text'} }")
        
        # 验证对话格式
        logger.info(f"{ctx}步骤1: 验证对话格式")
        if not self.validate_dialogue_format(text):
            logger.error(f"{ctx}对话格式验证失败")
            raise ValueError("文本格式不符合对话要求。请使用以下格式：\n人名（描述）：对话内容\n或\n人名：对话内容\n示例：婷婷（活泼感性）：哈喽，大家好！")
        logger.info(f"{ctx}对话格式验证通过")
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"{ctx}步骤2: TTS合成尝试 {attempt + 1}/{self.max_retries}")
                logger.info(f"{ctx}调用TTS客户端: text_length={len(text)}")
                audio_data = await self.tts_client.synthesize(text, **kwargs)
                logger.info(f"{ctx}TTS客户端返回: 音频数据大小={len(audio_data)} 字节")
                
                if len(audio_data) == 0:
                    logger.error(f"{ctx}TTS返回空音频数据")
                    raise ValueError("TTS返回空音频数据")
                
                logger.info(f"{ctx}=== TTS合成成功 ===")
                logger.info(f"{ctx}最终结果: 音频大小={len(audio_data)} 字节")
                return audio_data
                
            except Exception as e:
                logger.warning(f"{ctx}TTS合成失败 (尝试 {attempt + 1}/{self.max_retries})")
                logger.warning(f"{ctx}错误类型: {type(e).__name__}")
                logger.warning(f"{ctx}错误信息: {str(e)}")
                
                if attempt < self.max_retries - 1:
                    logger.info(f"{ctx}等待 {self.retry_delay} 秒后重试")
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.error(f"{ctx}所有重试尝试失败，抛出异常")
                    raise
    
    def validate_dialogue_format(self, text: str) -> bool:
        """验证对话格式"""
        import re
        import unicodedata
        # 统一规范化，避免不同来源文本的组合字符差异导致匹配失败
        text = unicodedata.normalize('NFC', text or '')
        lines = text.strip().split('\n')
        valid_lines = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 正则说明：
            # - 同时支持中文/英文冒号：[:：]
            # - 可选的人名后描述，支持中文/英文括号：（…）或 (…)
            #   形如：人名（描述）：内容  或  人名(描述): 内容
            # - 允许人名为中英文、数字等，最关键是能在第一个冒号前正确切分
            # with_desc:    角色 + （…）/ (…) + 冒号 + 内容
            # without_desc: 角色 + 冒号 + 内容
            if (re.match(r'^[^（(]+[（(][^）)]*[）)]\s*[:：]\s*.+$', line) or 
                re.match(r'^[^:：]+[:：]\s*.+$', line)):
                valid_lines += 1
            else:
                return False
        
        return valid_lines > 0
    
    def get_available_voices(self) -> List[str]:
        """获取可用音色列表（筛选bigtts类型）"""
        return [speaker for speaker in self.available_speakers if 'bigtts' in speaker]
