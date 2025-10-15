"""
任务管理服务
支持强幂等和超时处理
"""

import time
import asyncio
import logging
import threading
from sqlalchemy.exc import IntegrityError
from typing import Dict, Any, Optional
from ..models import get_session, TtsText, TtsAudio
from .tts_service import TTSServiceInterface
from .audio_service import AudioService
from ..exceptions import ConcurrencyQuotaExceeded

logger = logging.getLogger(__name__)

# 限制同时发起的TTS并发（基础限流）
# 4 workers × 2 = 8 全局并发，避免触发火山引擎配额限制
_TTS_CONCURRENCY_SEMA = threading.BoundedSemaphore(value=2)

class TaskService:
    """任务服务 - 支持强幂等和超时处理"""
    
    def __init__(self, tts_service, oss_client, monitor=None):
        self.tts_service = tts_service
        self.oss_client = oss_client
        self.monitor = monitor
    
    async def create_tts_task(self, text_id: int, user_id: int, **kwargs) -> Dict[str, Any]:
        """创建TTS任务 - 强幂等实现"""
        start_time = time.time()
        logger.info(f"=== 开始TTS任务 ===")
        logger.info(f"任务参数: text_id={text_id}, user_id={user_id}")
        logger.info(f"监控器状态: {self.monitor is not None}")
        
        try:
            # 获取文本内容
            logger.info(f"步骤1: 获取文本内容 - text_id={text_id}")
            with get_session() as s:
                text_row = s.query(TtsText).filter(
                    TtsText.id == text_id, 
                    TtsText.is_deleted == 0
                ).first()
                
                if not text_row:
                    logger.error(f"文本不存在: text_id={text_id}")
                    raise ValueError(f"文本不存在: text_id={text_id}")
                
                logger.info(f"文本信息: title='{text_row.title}', char_count={text_row.char_count}")
                logger.info(f"文本内容长度: {len(text_row.content)}")
                logger.info(f"文本内容预览: {text_row.content[:100]}...")
                
                # 检查幂等性 - 结合内容级与任务级
                logger.info(f"步骤2: 检查幂等性 - text_id={text_id}")
                leader_info = None
                if self.monitor:
                    # 先基于内容查找是否已有任务
                    leader_info = self.monitor.find_existing_by_content(text_row.content)
                    logger.info(f"内容幂等查找: {leader_info}")
                    # 注册当前任务（若需要执行）
                    logger.info(f"调用监控器start_task: text_id={text_id}")
                    should_execute = self.monitor.start_task(text_id, text_row.content)
                    logger.info(f"监控器返回结果: should_execute={should_execute}")
                    if not should_execute and leader_info:
                        existing_text_id = leader_info['existing_text_id']
                        existing_status = leader_info['status']
                        logger.info(f"幂等命中: existing_text_id={existing_text_id}, status={existing_status}")
                        # 计算目标OSS key
                        from ..tts_client import compute_audio_filename
                        filename = compute_audio_filename(text_row.title, text_row.char_count, 1)
                        object_key = f"audios/{text_row.title}/{filename}"
                        audio_service = AudioService(self.oss_client)
                        audio_url = audio_service.get_audio_url(object_key)
                        
                        if existing_status == 'completed':
                            # 若DB没有记录，补写记录
                            logger.info("幂等完成：补写数据库与完成事件给当前text_id")
                            existing_audio = s.query(TtsAudio).filter(
                                TtsAudio.text_id == text_id,
                                TtsAudio.oss_object_key == object_key,
                                TtsAudio.is_deleted == 0
                            ).first()
                            if not existing_audio:
                                audio_row = TtsAudio(
                                    text_id=text_id,
                                    user_id=user_id,
                                    filename=filename,
                                    oss_object_key=object_key,
                                    file_size=0,
                                    version_num=1
                                )
                                s.add(audio_row)
                                s.commit()
                            # 通知完成（让新text_id也有终态）
                            self.monitor.complete_task(text_id, audio_url)
                            return {
                                "success": True,
                                "text_id": text_id,
                                "skipped": True,
                                "message": "使用现有音频文件",
                                "follow_text_id": existing_text_id
                            }
                        else:
                            # 进行中：建立跟随关系，让新text_id收到同样事件
                            logger.info("幂等进行中：建立跟随关系")
                            self.monitor.link_task(text_id, existing_text_id)
                            return {
                                "success": True,
                                "text_id": text_id,
                                "skipped": True,
                                "message": "任务已在进行中，已跟随现有任务",
                                "follow_text_id": existing_text_id
                            }
                else:
                    logger.warning("监控器未配置，跳过幂等性检查")
                
                # 检查OSS是否已存在相同文件（幂等性检查）
                logger.info(f"步骤3: 检查OSS文件是否存在 - text_id={text_id}")
                import hashlib
                from ..tts_client import compute_audio_filename
                from ..oss import OssClient
                filename = compute_audio_filename(
                    text_row.title, 
                    text_row.char_count, 
                    1  # 总是使用版本1，确保幂等
                )
                # 标题规范化 + 内容哈希前缀，避免同标题不同内容冲突
                content_hash = hashlib.sha256(text_row.content.encode('utf-8')).hexdigest()[:8]
                safe_title = OssClient.sanitize_path_segment(text_row.title)
                object_key = f"audios/{safe_title}/{content_hash}/{filename}"
                logger.info(f"计算的文件名: {filename}")
                logger.info(f"OSS对象键: {object_key}")
                
                # 检查OSS文件是否已存在
                logger.info(f"检查OSS文件是否存在: {object_key}")
                oss_exists = self.oss_client.object_exists(object_key)
                logger.info(f"OSS文件存在检查结果: {oss_exists}")
                
                if oss_exists:
                    # 智能幂等检查：不仅检查存在，还要检查质量
                    logger.info(f"音频文件已存在，检查质量: {object_key}")
                    
                    # 获取OSS文件实际大小
                    try:
                        file_size = self.oss_client.get_object_size(object_key)
                        logger.info(f"获取OSS文件大小: {file_size} 字节")
                    except Exception as e:
                        logger.warning(f"获取OSS文件大小失败: {e}, 将重新生成")
                        file_size = 0
                    
                    # 质量检查：小于5KB视为损坏文件
                    MIN_VALID_AUDIO_SIZE = 5000
                    if file_size < MIN_VALID_AUDIO_SIZE:
                        # 发现损坏文件，自动清理并重新生成
                        logger.warning(f"🗑️  发现损坏音频文件(size={file_size}B < {MIN_VALID_AUDIO_SIZE}B)，删除重新生成: {object_key}")
                        try:
                            self.oss_client.bucket.delete_object(object_key)
                            logger.info(f"✅ 已删除损坏OSS文件: {object_key}")
                        except Exception as e:
                            logger.error(f"❌ 删除损坏OSS文件失败: {e}，仍将尝试重新生成")
                        
                        # 标记为不存在，继续正常生成流程
                        oss_exists = False
                    else:
                        # 文件正常，执行原有幂等逻辑
                        logger.info(f"✅ 音频文件有效(size={file_size}B)，跳过生成: {object_key}")
                        
                        # 检查数据库是否已有记录
                        logger.info(f"检查数据库音频记录: text_id={text_id}")
                        existing_audio = s.query(TtsAudio).filter(
                            TtsAudio.text_id == text_id,
                            TtsAudio.oss_object_key == object_key,
                            TtsAudio.is_deleted == 0
                        ).first()
                        
                        if existing_audio:
                            logger.info(f"找到现有音频记录: audio_id={existing_audio.id}")
                            # 使用现有记录
                            audio_id = existing_audio.id
                            file_size = existing_audio.file_size
                        else:
                            logger.info(f"创建新的音频记录: text_id={text_id}")
                            
                            # 创建新记录
                            audio_row = TtsAudio(
                                text_id=text_id,
                                user_id=user_id,
                                filename=filename,
                                oss_object_key=object_key,
                                file_size=file_size,  # 使用实际大小
                                version_num=1
                            )
                            s.add(audio_row)
                            s.commit()
                            audio_id = audio_row.id
                            logger.info(f"新音频记录创建成功: audio_id={audio_id}, file_size={file_size}")
                        
                        # 通知监控器完成
                        if self.monitor:
                            logger.info(f"通知监控器任务完成: text_id={text_id}")
                            audio_service = AudioService(self.oss_client)
                            audio_url = audio_service.get_audio_url(object_key)
                            logger.info(f"音频URL: {audio_url}")
                            self.monitor.complete_task(text_id, audio_url, filename)
                        
                        return {
                            "success": True,
                            "text_id": text_id,
                            "audio_id": audio_id,
                            "filename": filename,
                            "file_size": file_size,
                            "skipped": True,
                            "message": "使用现有音频文件"
                        }
                
                # 生成音频
                logger.info(f"步骤4: 开始TTS音频生成 - text_id={text_id}")
                logger.info(f"调用TTS服务: text_length={len(text_row.content)}")
                _TTS_CONCURRENCY_SEMA.acquire()
                try:
                    audio_data = await self.tts_service.synthesize_text(text_row.content, text_id=text_id)
                finally:
                    _TTS_CONCURRENCY_SEMA.release()
                audio_size = len(audio_data)
                logger.info(f"TTS生成完成: 音频数据大小={audio_size} 字节")
                if audio_size < 10240:
                    logger.warning(f"text_id={text_id} 合成音频异常偏小: size={audio_size} 字节")
                
                # 上传到OSS
                logger.info(f"步骤5: 上传音频到OSS - text_id={text_id}")
                logger.info(f"上传参数: object_key={object_key}, size={audio_size}")
                self.oss_client.upload_bytes(
                    object_key, 
                    audio_data, 
                    content_type='audio/mpeg'
                )
                logger.info(f"OSS上传完成: {object_key}")
                
                # 记录到数据库
                logger.info(f"步骤6: 保存音频记录到数据库 - text_id={text_id}")
                audio_row = TtsAudio(
                    text_id=text_id,
                    user_id=user_id,
                    filename=filename,
                    oss_object_key=object_key,
                    file_size=len(audio_data),
                    version_num=1
                )
                s.add(audio_row)
                try:
                    s.commit()
                    logger.info(f"数据库记录保存成功: audio_id={audio_row.id}")
                except IntegrityError:
                    s.rollback()
                    # 并发下已存在，复用已有记录
                    logger.warning("并发写入命中唯一约束，复用已存在音频记录")
                    existing_audio = s.query(TtsAudio).filter(
                        TtsAudio.oss_object_key == object_key,
                        TtsAudio.is_deleted == 0
                    ).first()
                    if existing_audio:
                        audio_row = existing_audio
                    else:
                        raise
                
                duration = time.time() - start_time
                logger.info(f"=== TTS任务完成 ===")
                logger.info(f"任务结果: text_id={text_id}, audio_id={audio_row.id}")
                logger.info(f"执行时间: {duration:.2f}s")
                logger.info(f"文件大小: {len(audio_data)} 字节")
                logger.info(f"文件名: {filename}")
                
                # 通知监控器完成
                if self.monitor:
                    logger.info(f"步骤7: 通知监控器任务完成 - text_id={text_id}")
                    audio_service = AudioService(self.oss_client)
                    audio_url = audio_service.get_audio_url(object_key)
                    logger.info(f"音频URL: {audio_url}")
                    self.monitor.complete_task(text_id, audio_url, filename)
                    logger.info(f"监控器通知完成")
                
                return {
                    "success": True,
                    "text_id": text_id,
                    "audio_id": audio_row.id,
                    "filename": filename,
                    "file_size": len(audio_data),
                    "duration": duration
                }
                
        except ConcurrencyQuotaExceeded as e:
            # 并发配额超限，延迟后重试
            duration = time.time() - start_time
            logger.warning(f"=== TTS任务配额超限 ===")
            logger.warning(f"text_id={text_id} 触发并发配额超限（错误码45000292）")
            logger.warning(f"执行时间: {duration:.2f}s")
            
            # 通知监控器失败（便于前端显示）
            if self.monitor:
                self.monitor.fail_task(text_id, f"配额超限，稍后自动重试: {str(e)}")
            
            # 延迟60秒后重新抛出，让调用方决定是否重试
            logger.info(f"延迟60秒以缓解配额压力...")
            await asyncio.sleep(60)
            raise
                
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"=== TTS任务失败 ===")
            logger.error(f"任务参数: text_id={text_id}, user_id={user_id}")
            logger.error(f"执行时间: {duration:.2f}s")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"错误信息: {str(e)}")
            logger.error(f"错误堆栈: {e.__traceback__}")
            
            # 通知监控器失败
            if self.monitor:
                logger.info(f"通知监控器任务失败: text_id={text_id}")
                self.monitor.fail_task(text_id, str(e))
            
            raise
