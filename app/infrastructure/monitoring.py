"""
任务监控基础设施
提供任务执行监控、SSE推送和强幂等功能
"""

import time
import logging
import hashlib
import threading
from collections import defaultdict
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"

@dataclass
class TaskInfo:
    text_id: int
    status: TaskStatus
    start_time: float
    completed_time: Optional[float] = None
    error_message: Optional[str] = None
    audio_url: Optional[str] = None
    idempotency_key: Optional[str] = None
    filename: Optional[str] = None

class TaskMonitor:
    """任务监控器 - 支持SSE推送和强幂等"""
    
    def __init__(self):
        self.stats = defaultdict(int)
        self.tasks: Dict[int, TaskInfo] = {}  # text_id -> TaskInfo
        self.idempotency_map: Dict[str, int] = {}  # idempotency_key -> text_id
        self.sse_listeners: Dict[int, List[Callable]] = defaultdict(list)  # text_id -> listeners
        # 跟随关系：leader -> followers；follower -> leader
        self.followers: Dict[int, List[int]] = defaultdict(list)
        self.follow_parent: Dict[int, int] = {}  # follower_id -> leader_id
        self.lock = threading.RLock()
        self.timeout_seconds = 40 * 60  # 40分钟超时
    
    def _generate_idempotency_key(self, text_content: str) -> str:
        """生成幂等键"""
        return hashlib.sha256(text_content.encode('utf-8')).hexdigest()
    
    def _notify_listeners(self, text_id: int, event_type: str, data: Dict[str, Any]):
        """通知SSE监听器"""
        with self.lock:
            listeners = self.sse_listeners.get(text_id, [])
            for listener in listeners:
                try:
                    listener(event_type, data)
                except Exception as e:
                    logger.error(f"SSE通知失败: text_id={text_id}, error={e}")
            # 将事件广播给所有跟随 text_id 的 follower
            follower_ids = list(self.followers.get(text_id, []))
            if follower_ids:
                for fid in follower_ids:
                    f_listeners = self.sse_listeners.get(fid, [])
                    f_data = dict(data)
                    f_data['text_id'] = fid
                    for listener in f_listeners:
                        try:
                            listener(event_type, f_data)
                        except Exception as e:
                            logger.error(f"SSE通知失败: follower_id={fid}, error={e}")

    def find_existing_by_content(self, text_content: str) -> Optional[Dict[str, Any]]:
        """根据内容幂等键查找已存在任务信息"""
        with self.lock:
            key = self._generate_idempotency_key(text_content)
            existing_id = self.idempotency_map.get(key)
            if not existing_id:
                return None
            ti = self.tasks.get(existing_id)
            status = ti.status.value if ti else None
            return {
                'existing_text_id': existing_id,
                'status': status
            }

    def link_task(self, follower_text_id: int, leader_text_id: int):
        """将 follower 挂靠到 leader，转发事件。若 follower 未注册，创建 processing 状态并发出 started 事件。"""
        with self.lock:
            if follower_text_id == leader_text_id:
                return
            self.follow_parent[follower_text_id] = leader_text_id
            if follower_text_id not in self.followers[leader_text_id]:
                self.followers[leader_text_id].append(follower_text_id)
            # 确保 follower 在任务表中存在（processing）
            if follower_text_id not in self.tasks:
                self.tasks[follower_text_id] = TaskInfo(
                    text_id=follower_text_id,
                    status=TaskStatus.PROCESSING,
                    start_time=time.time(),
                    idempotency_key=None
                )
                # 给 follower 发送 started
                self._notify_listeners(follower_text_id, "started", {
                    'text_id': follower_text_id,
                    'status': TaskStatus.PROCESSING.value
                })
    
    def start_task(self, text_id: int, text_content: str) -> bool:
        """开始任务 - 返回是否应该执行（幂等检查）"""
        logger.info(f"=== 监控器start_task调用 ===")
        logger.info(f"参数: text_id={text_id}, text_length={len(text_content)}")
        
        with self.lock:
            # 生成幂等键
            idempotency_key = self._generate_idempotency_key(text_content)
            logger.info(f"生成幂等键: {idempotency_key[:16]}...")
            
            # 检查是否已存在相同内容的任务
            logger.info(f"检查幂等性: idempotency_key={idempotency_key[:16]}...")
            if idempotency_key in self.idempotency_map:
                existing_text_id = self.idempotency_map[idempotency_key]
                logger.info(f"找到相同内容的现有任务: existing_text_id={existing_text_id}")
                
                if existing_text_id in self.tasks:
                    existing_task = self.tasks[existing_text_id]
                    logger.info(f"现有任务状态: {existing_task.status}")
                    
                    if existing_task.status in [TaskStatus.COMPLETED, TaskStatus.PROCESSING]:
                        logger.info(f"任务已存在且状态为{existing_task.status}，跳过执行")
                        return False
                else:
                    logger.warning(f"幂等键存在但任务记录不存在: existing_text_id={existing_text_id}")
            else:
                logger.info(f"未找到相同内容的现有任务，继续执行")
            
            # 检查当前text_id是否已有进行中的任务
            logger.info(f"检查当前text_id是否已有任务: text_id={text_id}")
            if text_id in self.tasks:
                existing_task = self.tasks[text_id]
                logger.info(f"当前text_id已有任务，状态: {existing_task.status}")
                
                if existing_task.status == TaskStatus.PROCESSING:
                    logger.warning(f"任务已在进行中: text_id={text_id}")
                    return False
            else:
                logger.info(f"当前text_id无现有任务，可以创建新任务")
            
            # 创建新任务
            logger.info(f"创建新任务: text_id={text_id}")
            task_info = TaskInfo(
                text_id=text_id,
                status=TaskStatus.PROCESSING,
                start_time=time.time(),
                idempotency_key=idempotency_key
            )
            
            self.tasks[text_id] = task_info
            self.idempotency_map[idempotency_key] = text_id
            self.stats['tasks_started'] += 1
            
            logger.info(f"任务创建成功: text_id={text_id}")
            logger.info(f"当前任务总数: {len(self.tasks)}")
            logger.info(f"当前统计: {dict(self.stats)}")
            
            # 通知监听器
            logger.info(f"通知监听器: text_id={text_id}")
            self._notify_listeners(text_id, "started", {
                "text_id": text_id,
                "status": TaskStatus.PROCESSING.value
            })
            
            logger.info(f"=== 监控器start_task完成，返回True ===")
            return True
    
    def complete_task(self, text_id: int, audio_url: str, filename: Optional[str] = None):
        """完成任务"""
        with self.lock:
            if text_id not in self.tasks:
                logger.warning(f"任务不存在: text_id={text_id}")
                return
            
            task_info = self.tasks[text_id]
            task_info.status = TaskStatus.COMPLETED
            task_info.completed_time = time.time()
            task_info.audio_url = audio_url
            task_info.filename = filename
            
            duration = task_info.completed_time - task_info.start_time
            self.stats['tasks_completed'] += 1
            self.stats['total_duration'] += duration
            
            logger.info(f"任务完成: text_id={text_id}, duration={duration:.2f}s")
            
            # 通知监听器
            self._notify_listeners(text_id, "completed", {
                "text_id": text_id,
                "status": TaskStatus.COMPLETED.value,
                "audio_url": audio_url,
                "filename": filename,
                "duration": duration
            })
    
    def fail_task(self, text_id: int, error_message: str):
        """任务失败"""
        with self.lock:
            if text_id not in self.tasks:
                logger.warning(f"任务不存在: text_id={text_id}")
                return
            
            task_info = self.tasks[text_id]
            task_info.status = TaskStatus.FAILED
            task_info.completed_time = time.time()
            task_info.error_message = error_message
            
            duration = task_info.completed_time - task_info.start_time
            self.stats['tasks_failed'] += 1
            self.stats['total_duration'] += duration
            
            logger.error(f"任务失败: text_id={text_id}, duration={duration:.2f}s, error={error_message}")
            
            # 通知监听器
            self._notify_listeners(text_id, "failed", {
                "text_id": text_id,
                "status": TaskStatus.FAILED.value,
                "error_message": error_message,
                "duration": duration
            })
    
    def timeout_task(self, text_id: int):
        """任务超时"""
        with self.lock:
            if text_id not in self.tasks:
                return
            
            task_info = self.tasks[text_id]
            task_info.status = TaskStatus.TIMEOUT
            task_info.completed_time = time.time()
            task_info.error_message = "任务超时"
            
            duration = task_info.completed_time - task_info.start_time
            self.stats['tasks_failed'] += 1
            self.stats['total_duration'] += duration
            
            logger.warning(f"任务超时: text_id={text_id}, duration={duration:.2f}s")
            
            # 通知监听器
            self._notify_listeners(text_id, "timeout", {
                "text_id": text_id,
                "status": TaskStatus.TIMEOUT.value,
                "error_message": "任务超时",
                "duration": duration
            })
    
    def get_task_status(self, text_id: int) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        with self.lock:
            if text_id not in self.tasks:
                return None
            
            task_info = self.tasks[text_id]
            result = {
                "text_id": text_id,
                "status": task_info.status.value,
                "start_time": task_info.start_time,
                "completed_time": task_info.completed_time,
                "error_message": task_info.error_message,
                "audio_url": task_info.audio_url,
                "filename": task_info.filename
            }
            
            if task_info.completed_time:
                result["duration"] = task_info.completed_time - task_info.start_time
            
            return result
    
    def add_sse_listener(self, text_id: int, listener: Callable):
        """添加SSE监听器"""
        with self.lock:
            self.sse_listeners[text_id].append(listener)
    
    def remove_sse_listener(self, text_id: int, listener: Callable):
        """移除SSE监听器"""
        with self.lock:
            if text_id in self.sse_listeners:
                try:
                    self.sse_listeners[text_id].remove(listener)
                except ValueError:
                    pass
    
    def check_timeouts(self):
        """检查超时任务"""
        current_time = time.time()
        with self.lock:
            for text_id, task_info in list(self.tasks.items()):
                if (task_info.status == TaskStatus.PROCESSING and 
                    current_time - task_info.start_time > self.timeout_seconds):
                    self.timeout_task(text_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self.lock:
            active_tasks = sum(1 for t in self.tasks.values() if t.status == TaskStatus.PROCESSING)
            total_tasks = len(self.tasks)
            avg_duration = 0
            if self.stats['tasks_completed'] > 0:
                avg_duration = self.stats['total_duration'] / self.stats['tasks_completed']
            
            return {
                'active_tasks': active_tasks,
                'total_tasks': total_tasks,
                'tasks_started': self.stats['tasks_started'],
                'tasks_completed': self.stats['tasks_completed'],
                'tasks_failed': self.stats['tasks_failed'],
                'average_duration': avg_duration
            }
    
    def get_active_tasks(self) -> List[int]:
        """获取活跃任务列表"""
        with self.lock:
            return [text_id for text_id, task_info in self.tasks.items() 
                   if task_info.status == TaskStatus.PROCESSING]
    
    # 向后兼容的方法
    def record_success(self, task_id: int, file_size: int, duration: float):
        """记录成功 - 向后兼容"""
        self.stats['tasks_completed'] += 1
        self.stats['total_duration'] += duration
        self.stats['total_file_size'] += file_size
        if self.stats['tasks_completed'] > 0:
            self.stats['avg_duration'] = self.stats['total_duration'] / self.stats['tasks_completed']
        logger.info(f"任务完成: task_id={task_id}, duration={duration:.2f}s, size={file_size}")
    
    def record_error(self, task_id: int, error: str, duration: float):
        """记录错误 - 向后兼容"""
        self.stats['tasks_failed'] += 1
        logger.error(f"任务失败: task_id={task_id}, duration={duration:.2f}s, error={error}")
