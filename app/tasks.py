import concurrent.futures
import threading
import asyncio
from typing import Callable, Optional
from flask import current_app

from .models import get_session, TtsAudio, TtsText


class BoundedExecutor:
    def __init__(self, max_workers: int = 4, queue_capacity: int = 64):
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tts-bg")
        self._sema = threading.BoundedSemaphore(value=queue_capacity)

    def submit(self, fn: Callable, *args, **kwargs):
        self._sema.acquire()
        def _run():
            try:
                return fn(*args, **kwargs)
            finally:
                self._sema.release()
        return self._executor.submit(_run)


executor = BoundedExecutor()

def run_tts_and_upload(text_id: int, user_id: int, app):
    """运行对话TTS任务并上传音频 - 使用新的服务层"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"=== 后台任务开始执行 ===")
    logger.info(f"任务参数: text_id={text_id}, user_id={user_id}")
    
    # 在应用上下文中运行（使用传入的真实 app 对象）
    try:
        app_name = getattr(app, 'name', 'unknown')
        logger.info(f"准备推送应用上下文: app={app_name}")
    except Exception:
        pass
    with app.app_context():
        try:
            logger.info(f"步骤1: 获取服务配置")
            # 获取服务
            task_service = app.config['TASK_SERVICE']
            monitor = app.config['MONITOR']
            logger.info(f"服务获取成功: task_service={task_service is not None}, monitor={monitor is not None}")
            
            # 运行异步任务
            logger.info(f"步骤2: 创建异步事件循环")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logger.info(f"事件循环创建成功")
            
            try:
                logger.info(f"步骤3: 执行异步TTS任务")
                result = loop.run_until_complete(
                    task_service.create_tts_task(text_id, user_id)
                )
                logger.info(f"=== 后台任务执行成功 ===")
                logger.info(f"任务结果: {result}")
                print(f"TTS任务成功: {result}")
            finally:
                logger.info(f"步骤4: 关闭事件循环")
                loop.close()
                logger.info(f"事件循环已关闭")
                
        except Exception as e:
            logger.error(f"=== 后台任务执行失败 ===")
            logger.error(f"任务参数: text_id={text_id}, user_id={user_id}")
            logger.error(f"错误类型: {type(e).__name__}")
            logger.error(f"错误信息: {str(e)}")
            logger.error(f"错误堆栈: {e.__traceback__}")
            print(f"TTS任务失败: text_id={text_id}, error={e}")
            
            # 通知监控器失败
            try:
                logger.info(f"通知监控器任务失败")
                monitor = app.config.get('MONITOR')
                if monitor:
                    monitor.fail_task(text_id, str(e))
                logger.info(f"监控器通知完成")
            except Exception as monitor_error:
                logger.error(f"监控器通知失败: {monitor_error}")

    logger.info(f"=== 后台任务执行结束 ===")
