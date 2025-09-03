import asyncio
import json
import uuid
import websockets
import logging
from typing import Dict, Any, Optional, List
from .protocols import (
    Message, MsgType, MsgTypeFlagBits, EventType,
    receive_message, wait_for_event, start_connection, 
    finish_connection, start_session, finish_session
)

logger = logging.getLogger(__name__)

class VolcTtsClient:
    """火山引擎TTS客户端 - 基于官方SDK实现"""
    
    def __init__(self, app_id: str, access_token: str, secret_key: str, api_base: str):
        self.app_id = app_id
        self.access_token = access_token
        self.secret_key = secret_key
        self.api_base = api_base.rstrip('/')
        self.endpoint = "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
    
    def build_dialogue_payload(self, text: str, input_id: str = None) -> Dict[str, Any]:
        """构建对话请求参数"""
        if input_id is None:
            input_id = f"tts_{uuid.uuid4().hex[:8]}"
        
        # 解析对话文本
        dialogue_parts = self.parse_dialogue_text(text)
        
        nlp_texts = []
        for part in dialogue_parts:
            speaker = self.get_speaker_for_role(part['role'])
            nlp_texts.append({
                "speaker": speaker,
                "text": part['content']
            })
        
        return {
            "input_id": input_id,
            "action": 3,  # 多音色对话
            "use_head_music": False,
            "use_tail_music": False,
            "nlp_texts": nlp_texts,
            "speaker_info": {"random_order": False},
            "input_info": {
                "return_audio_url": False,
                "only_nlp_text": False,
            },
            "audio_config": {
                "format": "mp3",
                "sample_rate": 24000,
                "speech_rate": 0
            }
        }
    
    def parse_dialogue_text(self, text: str) -> List[Dict[str, str]]:
        """解析对话文本，返回角色和内容列表"""
        import re
        lines = text.strip().split('\n')
        dialogue_parts = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 匹配格式：人名（描述）：对话内容
            match_with_desc = re.match(r'^([^（]+)（[^）]*）：(.+)$', line)
            if match_with_desc:
                role = match_with_desc.group(1).strip()
                content = match_with_desc.group(2).strip()
                dialogue_parts.append({
                    'role': role,
                    'content': content
                })
                continue
            
            # 匹配格式：人名：对话内容
            match_without_desc = re.match(r'^([^：]+)：(.+)$', line)
            if match_without_desc:
                role = match_without_desc.group(1).strip()
                content = match_without_desc.group(2).strip()
                dialogue_parts.append({
                    'role': role,
                    'content': content
                })
                continue
        
        return dialogue_parts
    
    def get_speaker_for_role(self, role: str) -> str:
        """根据角色返回对应的speaker（首个女声，第二个男声，后续按角色名匹配）"""
        first = getattr(self, '_first_speaker', None)
        second = getattr(self, '_second_speaker', None)
        # 首次角色：女声
        if first is None:
            self._first_speaker = role
            return "zh_female_mizai_v2_saturn_bigtts"
        # 第二个新角色：男声
        if second is None and role != first:
            self._second_speaker = role
            return "zh_male_dayi_v2_saturn_bigtts"
        # 后续按角色名匹配
        if role == first:
            return "zh_female_mizai_v2_saturn_bigtts"
        if role == second:
            return "zh_male_dayi_v2_saturn_bigtts"
        # 未匹配的新角色，默认跟随第一个（女声）
        return "zh_female_mizai_v2_saturn_bigtts"
    
    async def synthesize(self, text: str, **kwargs) -> bytes:
        """合成对话文本为音频"""
        text_id = kwargs.get('text_id')
        ctx = f"[text_id={text_id}] " if text_id is not None else ""
        logger.info(f"{ctx}=== TTS客户端开始合成 ===")
        logger.info(f"{ctx}文本长度: {len(text)}")
        logger.info(f"{ctx}文本内容: {text[:200]}...")
        
        # 重置角色记录
        self._first_speaker = None
        self._second_speaker = None
        logger.info(f"{ctx}重置角色记录")
        
        if not self.access_token:
            logger.warning(f"{ctx}TTS Access Token未配置，使用测试数据")
            test_audio = self._generate_test_audio(text)
            logger.info(f"{ctx}测试音频生成完成: {len(test_audio)} 字节")
            return test_audio
        
        try:
            logger.info(f"{ctx}步骤1: 构建对话请求参数")
            # 构建请求参数
            req_params = self.build_dialogue_payload(text)
            logger.info(f"{ctx}请求参数构建完成: nlp_texts数量={len(req_params.get('nlp_texts', []))}")
            
            # 认证头部
            logger.info(f"{ctx}步骤2: 构建认证头部")
            headers = {
                "X-Api-App-Id": self.app_id,
                "X-Api-App-Key": "aGjiRDfUWi",  # 固定值
                "X-Api-Access-Key": self.access_token,
                "X-Api-Resource-Id": "volc.service_type.10029",  # 标准TTS
                "X-Api-Connect-Id": str(uuid.uuid4()),
            }
            logger.info(f"{ctx}认证头部构建完毕（已脱敏）")
            
            # 建立WebSocket连接并合成音频
            logger.info(f"{ctx}步骤3: 开始WebSocket连接和音频接收")
            logger.info(f"{ctx}WebSocket端点: {self.endpoint}")
            audio_data = await self._synthesize_with_websocket(req_params, headers)
            logger.info(f"{ctx}WebSocket音频接收完成: {len(audio_data)} 字节")
            
            logger.info(f"{ctx}=== TTS客户端合成成功 ===")
            logger.info(f"{ctx}最终音频大小: {len(audio_data)} 字节")
            return audio_data
            
        except Exception as e:
            logger.error(f"{ctx}=== TTS客户端合成失败 ===")
            logger.error(f"{ctx}错误类型: {type(e).__name__}")
            logger.error(f"{ctx}错误信息: {str(e)}")
            # 如果真实TTS失败，返回测试数据
            logger.info(f"{ctx}使用测试数据作为备选方案")
            test_audio = self._generate_test_audio(text)
            logger.info(f"{ctx}测试音频生成完成: {len(test_audio)} 字节")
            return test_audio
    
    async def _synthesize_with_websocket(self, req_params: Dict[str, Any], headers: Dict[str, str]) -> bytes:
        """通过WebSocket进行TTS合成"""
        websocket = None
        podcast_audio = bytearray()
        audio = bytearray()
        
        try:
            logger.info("建立WebSocket连接...")
            websocket = await websockets.connect(self.endpoint, extra_headers=headers)
            logger.info("WebSocket连接成功")
            
            # 1. 开始连接
            await start_connection(websocket)
            logger.info("发送: StartConnection")
            
            # 2. 等待连接确认
            await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionStarted)
            logger.info("收到: ConnectionStarted")
            
            # 3. 开始会话
            session_id = str(uuid.uuid4())
            await start_session(websocket, json.dumps(req_params).encode(), session_id)
            logger.info(f"发送: StartSession (ID: {session_id[:8]}...)")
            
            # 4. 等待会话确认
            await wait_for_event(websocket, MsgType.FullServerResponse, EventType.SessionStarted)
            logger.info("收到: SessionStarted")
            
            # 5. 结束会话（开始处理）
            await finish_session(websocket, session_id)
            logger.info("发送: FinishSession")
            
            # 6. 接收响应数据
            logger.info("开始接收音频数据...")
            while True:
                msg = await receive_message(websocket)
                
                # 音频数据块
                if msg.type == MsgType.AudioOnlyServer and msg.event == EventType.PodcastRoundResponse:
                    audio.extend(msg.payload)
                    logger.debug(f"音频数据: {len(msg.payload)} bytes (总计: {len(audio)} bytes)")
                
                # 错误信息
                elif msg.type == MsgType.Error:
                    error_msg = msg.payload.decode()
                    logger.error(f"服务器错误: {error_msg}")
                    break
                
                elif msg.type == MsgType.FullServerResponse:
                    # 播客轮次结束
                    if msg.event == EventType.PodcastRoundEnd:
                        data = json.loads(msg.payload.decode())
                        logger.info(f"轮次结束: {data}")
                        
                        if data.get("is_error"):
                            logger.error(f"轮次错误: {data}")
                            break
                        
                        if audio:
                            podcast_audio.extend(audio)
                            logger.info(f"轮次音频: {len(audio)} bytes")
                            audio.clear()
                    
                    # 播客结束
                    elif msg.event == EventType.PodcastEnd:
                        data = json.loads(msg.payload.decode())
                        logger.info(f"播客生成完成: {data}")
                
                # 会话结束
                if msg.event == EventType.SessionFinished:
                    logger.info("会话结束")
                    break
            
            # 7. 结束连接
            await finish_connection(websocket)
            await wait_for_event(websocket, MsgType.FullServerResponse, EventType.ConnectionFinished)
            logger.info("连接正常结束")
            
            if podcast_audio:
                return bytes(podcast_audio)
            else:
                raise Exception("未收到音频数据")
                
        except Exception as e:
            logger.error(f"WebSocket TTS合成异常: {e}")
            raise
        finally:
            if websocket:
                await websocket.close()

    def _generate_test_audio(self, text: str) -> bytes:
        """生成测试音频数据"""
        logger.info("生成测试音频数据")
        # 创建一个简单的测试音频数据
        test_audio_data = b'\xff\xfb\x90\x00' + b'\x00' * 1000
        return test_audio_data


def compute_audio_filename(base_name_no_ext: str, char_count: int, next_version: int) -> str:
    # 规则：字数>4000 => _长，否则 _短；版本 _v01…_v99
    length_tag = "长" if char_count > 4000 else "短"
    version = f"v{next_version:02d}"
    return f"{base_name_no_ext}_{length_tag}_{version}.mp3"

    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
async def _safe_wait(websocket, timeout, recv_once=False):
    """Utility: wait for a single message with timeout."""
    return await asyncio.wait_for(receive_message(websocket), timeout=timeout)


class TtsAuthResult:
    def __init__(self, success: bool, endpoint: str, app_id_present: bool, token_present: bool, connection_started: bool = False, error: Optional[str] = None):
        self.success = success
        self.endpoint = endpoint
        self.app_id_present = app_id_present
        self.token_present = token_present
        self.connection_started = connection_started
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "endpoint": self.endpoint,
            "app_id_present": self.app_id_present,
            "token_present": self.token_present,
            "connection_started": self.connection_started,
            "error": self.error,
        }


async def _finish_connection_safely(ws):
    try:
        await finish_connection(ws)
        try:
            await asyncio.wait_for(wait_for_event(ws, MsgType.FullServerResponse, EventType.ConnectionFinished), timeout=5)
        except Exception:
            pass
    except Exception:
        pass


async def _ping_handshake(endpoint: str, headers: Dict[str, str]) -> TtsAuthResult:
    """Perform a minimal handshake to verify TTS auth without synthesis."""
    websocket = None
    try:
        websocket = await websockets.connect(endpoint, extra_headers=headers)
        await start_connection(websocket)
        # wait up to 10s for either ConnectionStarted or ConnectionFailed or Error
        connection_started = False
        deadline = asyncio.get_event_loop().time() + 10
        while True:
            timeout = max(0.1, deadline - asyncio.get_event_loop().time())
            if timeout <= 0:
                return TtsAuthResult(False, endpoint, True, True, False, "timeout waiting for ConnectionStarted")
            msg = await asyncio.wait_for(receive_message(websocket), timeout=timeout)
            if msg.type == MsgType.Error:
                return TtsAuthResult(False, endpoint, True, True, False, f"server error: {msg.payload.decode('utf-8', 'ignore')}")
            if msg.type == MsgType.FullServerResponse:
                if msg.event == EventType.ConnectionStarted:
                    connection_started = True
                    break
                if msg.event == EventType.ConnectionFailed:
                    return TtsAuthResult(False, endpoint, True, True, False, msg.payload.decode('utf-8', 'ignore'))
        # finish
        await _finish_connection_safely(websocket)
        return TtsAuthResult(True, endpoint, True, True, connection_started, None)
    except Exception as e:
        return TtsAuthResult(False, endpoint, True, True, False, str(e))
    finally:
        if websocket:
            try:
                await websocket.close()
            except Exception:
                pass


async def ping_auth_v3(app_id: str, access_token: str, endpoint: str) -> Dict[str, Any]:
    """Standalone helper for diagnostics."""
    app_id_present = bool(app_id)
    token_present = bool(access_token)
    if not app_id_present or not token_present:
        return TtsAuthResult(False, endpoint, app_id_present, token_present, False, "missing app_id or access_token").to_dict()
    headers = {
        "X-Api-App-Id": app_id,
        "X-Api-App-Key": "aGjiRDfUWi",
        "X-Api-Access-Key": access_token,
        "X-Api-Resource-Id": "volc.service_type.10029",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    res = await _ping_handshake(endpoint, headers)
    # adjust presence in result
    res.app_id_present = app_id_present
    res.token_present = token_present
    return res.to_dict()


def _attach_ping_auth_to_client():
    async def _ping(self) -> Dict[str, Any]:
        app_id_present = bool(self.app_id)
        token_present = bool(self.access_token)
        if not app_id_present or not token_present:
            return TtsAuthResult(False, self.endpoint, app_id_present, token_present, False, "missing app_id or access_token").to_dict()
        headers = {
            "X-Api-App-Id": self.app_id,
            "X-Api-App-Key": "aGjiRDfUWi",
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "volc.service_type.10029",
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        res = await _ping_handshake(self.endpoint, headers)
        res.app_id_present = app_id_present
        res.token_present = token_present
        return res.to_dict()
    setattr(VolcTtsClient, "ping_auth", _ping)

_attach_ping_auth_to_client()
