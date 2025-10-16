"""
Redis 版本任务监控器
"""

import json
import time
import logging
import hashlib
import threading
from collections import defaultdict
from typing import Dict, Any, Callable, Optional, List

from redis import Redis
from redis.client import PubSub
from redis.exceptions import RedisError

from .monitoring import TaskStatus, TaskMonitorProtocol

logger = logging.getLogger(__name__)


class RedisTaskMonitor(TaskMonitorProtocol):
    """基于 Redis 的任务监控器，实现跨进程共享"""

    def __init__(self, redis_client: Redis, namespace: str = "task_monitor"):
        self.redis = redis_client
        self.namespace = namespace
        self.timeout_seconds = 40 * 60

        self._local_lock = threading.RLock()
        self._listeners: Dict[int, List[Callable]] = defaultdict(list)

        self._pubsub: Optional[PubSub] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._ensure_event_listener()

    # ========== 公共接口 ==========

    def find_existing_by_content(self, text_content: str) -> Optional[Dict[str, Any]]:
        key = self._generate_idempotency_key(text_content)
        existing = self.redis.hget(self._idempotency_hash(), key)
        if not existing:
            return None
        status = self.redis.hget(self._task_key(existing), "status")
        return {
            "existing_text_id": int(existing),
            "status": status
        }

    def start_task(self, text_id: int, text_content: str) -> bool:
        now = time.time()
        idempotency_key = self._generate_idempotency_key(text_content)
        lock_name = self._lock_name(idempotency_key)
        try:
            with self.redis.lock(lock_name, blocking_timeout=5, timeout=30):
                existing = self.redis.hget(self._idempotency_hash(), idempotency_key)
                if existing:
                    status = self.redis.hget(self._task_key(existing), "status")
                    if status in (TaskStatus.COMPLETED.value, TaskStatus.PROCESSING.value):
                        return False

                current_status = self.redis.hget(self._task_key(text_id), "status")
                if current_status == TaskStatus.PROCESSING.value:
                    return False

                mapping = {
                    "text_id": text_id,
                    "status": TaskStatus.PROCESSING.value,
                    "start_time": now,
                    "idempotency_key": idempotency_key,
                    "completed_time": "",
                    "error_message": "",
                    "audio_url": "",
                    "filename": "",
                    "stage": "queued"
                }

                pipe = self.redis.pipeline()
                pipe.hset(self._idempotency_hash(), idempotency_key, text_id)
                pipe.hset(self._task_key(text_id), mapping=mapping)
                pipe.sadd(self._active_set(), text_id)
                pipe.sadd(self._all_set(), text_id)
                pipe.hincrby(self._stats_hash(), "tasks_started", 1)
                pipe.publish(self._event_channel(text_id), json.dumps({
                    "event": "started",
                    "text_id": text_id,
                    "status": TaskStatus.PROCESSING.value,
                    "stage": "queued"
                }))
                pipe.execute()
                return True
        except RedisError as exc:
            logger.error(f"Redis start_task 失败: text_id={text_id}, err={exc}")
            raise

    def complete_task(self, text_id: int, audio_url: str, filename: Optional[str] = None):
        now = time.time()
        task_key = self._task_key(text_id)

        try:
            with self.redis.lock(self._lock_name(f"task:{text_id}"), blocking_timeout=5, timeout=30):
                data = self.redis.hgetall(task_key)
                if not data:
                    logger.warning(f"RedisTaskMonitor.complete_task 找不到任务: text_id={text_id}")
                    return

                start_time = float(data.get("start_time", now))
                duration = max(0.0, now - start_time)
                mapping = {
                    "status": TaskStatus.COMPLETED.value,
                    "completed_time": now,
                    "audio_url": audio_url,
                    "filename": filename or data.get("filename", ""),
                    "stage": "done"
                }

                pipe = self.redis.pipeline()
                pipe.hset(task_key, mapping=mapping)
                pipe.srem(self._active_set(), text_id)
                pipe.hincrby(self._stats_hash(), "tasks_completed", 1)
                pipe.hincrbyfloat(self._stats_hash(), "total_duration", duration)
                pipe.publish(self._event_channel(text_id), json.dumps({
                    "event": "completed",
                    "text_id": text_id,
                    "status": TaskStatus.COMPLETED.value,
                    "stage": "done",
                    "audio_url": audio_url,
                    "filename": filename,
                    "duration": duration
                }))
                pipe.execute()
        except RedisError as exc:
            logger.error(f"Redis complete_task 失败: text_id={text_id}, err={exc}")
            raise

    def fail_task(self, text_id: int, error_message: str):
        now = time.time()
        task_key = self._task_key(text_id)

        try:
            with self.redis.lock(self._lock_name(f"task:{text_id}"), blocking_timeout=5, timeout=30):
                data = self.redis.hgetall(task_key)
                if not data:
                    logger.warning(f"RedisTaskMonitor.fail_task 找不到任务: text_id={text_id}")
                    return

                start_time = float(data.get("start_time", now))
                duration = max(0.0, now - start_time)

                mapping = {
                    "status": TaskStatus.FAILED.value,
                    "completed_time": now,
                    "error_message": error_message,
                    "stage": "done"
                }

                pipe = self.redis.pipeline()
                pipe.hset(task_key, mapping=mapping)
                pipe.srem(self._active_set(), text_id)
                pipe.hincrby(self._stats_hash(), "tasks_failed", 1)
                pipe.hincrbyfloat(self._stats_hash(), "total_duration", duration)
                pipe.publish(self._event_channel(text_id), json.dumps({
                    "event": "failed",
                    "text_id": text_id,
                    "status": TaskStatus.FAILED.value,
                    "stage": "done",
                    "error_message": error_message,
                    "duration": duration
                }))
                pipe.execute()
        except RedisError as exc:
            logger.error(f"Redis fail_task 失败: text_id={text_id}, err={exc}")
            raise

    def timeout_task(self, text_id: int):
        now = time.time()
        task_key = self._task_key(text_id)

        try:
            with self.redis.lock(self._lock_name(f"task:{text_id}"), blocking_timeout=5, timeout=30):
                data = self.redis.hgetall(task_key)
                if not data:
                    return

                start_time = float(data.get("start_time", now))
                duration = max(0.0, now - start_time)

                mapping = {
                    "status": TaskStatus.TIMEOUT.value,
                    "completed_time": now,
                    "error_message": "任务超时",
                    "stage": "done"
                }

                pipe = self.redis.pipeline()
                pipe.hset(task_key, mapping=mapping)
                pipe.srem(self._active_set(), text_id)
                pipe.hincrby(self._stats_hash(), "tasks_failed", 1)
                pipe.hincrbyfloat(self._stats_hash(), "total_duration", duration)
                pipe.publish(self._event_channel(text_id), json.dumps({
                    "event": "timeout",
                    "text_id": text_id,
                    "status": TaskStatus.TIMEOUT.value,
                    "stage": "done",
                    "error_message": "任务超时",
                    "duration": duration
                }))
                pipe.execute()
        except RedisError as exc:
            logger.error(f"Redis timeout_task 失败: text_id={text_id}, err={exc}")
            raise

    def get_task_status(self, text_id: int) -> Optional[Dict[str, Any]]:
        data = self.redis.hgetall(self._task_key(text_id))
        if not data:
            return None
        status = data.get("status")
        start_time = float(data.get("start_time", 0) or 0)
        completed_time = data.get("completed_time")
        stage = data.get("stage") or ("done" if data.get("completed_time") else "queued")
        result = {
            "text_id": int(text_id),
            "status": status,
            "start_time": start_time,
            "completed_time": float(completed_time) if completed_time else None,
            "error_message": data.get("error_message") or None,
            "audio_url": data.get("audio_url") or None,
            "filename": data.get("filename") or None,
            "stage": stage
        }
        if result["completed_time"]:
            result["duration"] = result["completed_time"] - start_time
        return result

    def update_stage(self, text_id: int, stage: str) -> None:
        task_key = self._task_key(text_id)
        try:
            status = self.redis.hget(task_key, "status") or TaskStatus.PROCESSING.value
            pipe = self.redis.pipeline()
            pipe.hset(task_key, "stage", stage)
            pipe.publish(self._event_channel(text_id), json.dumps({
                "event": "stage",
                "text_id": text_id,
                "status": status,
                "stage": stage
            }))
            pipe.execute()
        except RedisError as exc:
            logger.error(f"Redis update_stage 失败: text_id={text_id}, stage={stage}, err={exc}")

    def add_sse_listener(self, text_id: int, listener: Callable):
        with self._local_lock:
            self._listeners[text_id].append(listener)

    def remove_sse_listener(self, text_id: int, listener: Callable):
        with self._local_lock:
            listeners = self._listeners.get(text_id)
            if not listeners:
                return
            try:
                listeners.remove(listener)
            except ValueError:
                pass

    def check_timeouts(self):
        try:
            active_ids = self.redis.smembers(self._active_set())
            if not active_ids:
                return
            now = time.time()
            for tid in active_ids:
                task_key = self._task_key(tid)
                status = self.redis.hget(task_key, "status")
                if status != TaskStatus.PROCESSING.value:
                    continue
                start = float(self.redis.hget(task_key, "start_time") or now)
                if now - start > self.timeout_seconds:
                    self.timeout_task(int(tid))
        except RedisError as exc:
            logger.error(f"Redis check_timeouts 失败: {exc}")

    def get_stats(self) -> Dict[str, Any]:
        stats = self.redis.hgetall(self._stats_hash())
        tasks_started = int(stats.get("tasks_started", 0) or 0)
        tasks_completed = int(stats.get("tasks_completed", 0) or 0)
        tasks_failed = int(stats.get("tasks_failed", 0) or 0)
        total_duration = float(stats.get("total_duration", 0) or 0.0)

        active_count = self.redis.scard(self._active_set())
        total_tasks = self.redis.scard(self._all_set())
        average_duration = total_duration / tasks_completed if tasks_completed > 0 else 0.0

        return {
            "active_tasks": active_count,
            "total_tasks": total_tasks,
            "tasks_started": tasks_started,
            "tasks_completed": tasks_completed,
            "tasks_failed": tasks_failed,
            "average_duration": average_duration
        }

    def get_active_tasks(self) -> List[int]:
        ids = self.redis.smembers(self._active_set())
        return [int(i) for i in ids] if ids else []

    def link_task(self, follower_text_id: int, leader_text_id: int):
        if follower_text_id == leader_text_id:
            return
        now = time.time()
        try:
            with self.redis.lock(self._lock_name(f"link:{leader_text_id}"), blocking_timeout=5, timeout=30):
                follower_key = self._task_key(follower_text_id)
                data = self.redis.hgetall(follower_key)
                pipe = self.redis.pipeline()
                if not data:
                    pipe.hset(follower_key, mapping={
                        "text_id": follower_text_id,
                        "status": TaskStatus.PROCESSING.value,
                        "start_time": now,
                        "idempotency_key": "",
                        "completed_time": "",
                        "error_message": "",
                        "audio_url": "",
                        "filename": "",
                        "stage": "running"
                    })
                else:
                    pipe.hset(follower_key, mapping={
                        "status": TaskStatus.PROCESSING.value,
                        "start_time": now,
                        "stage": "running"
                    })

                pipe.hset(self._follow_parent_hash(), follower_text_id, leader_text_id)
                pipe.sadd(self._followers_set(leader_text_id), follower_text_id)
                pipe.sadd(self._active_set(), follower_text_id)
                pipe.sadd(self._all_set(), follower_text_id)
                pipe.publish(self._event_channel(follower_text_id), json.dumps({
                    "event": "started",
                    "text_id": follower_text_id,
                    "status": TaskStatus.PROCESSING.value,
                    "stage": "running"
                }))
                pipe.execute()
        except RedisError as exc:
            logger.error(f"Redis link_task 失败: follower={follower_text_id}, leader={leader_text_id}, err={exc}")
            raise

    # ========== 内部方法 ==========

    def _ensure_event_listener(self):
        if self._listener_thread and self._listener_thread.is_alive():
            return
        self._pubsub = self.redis.pubsub()
        self._pubsub.psubscribe(self._event_channel("*"))
        self._listener_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._listener_thread.start()

    def _event_loop(self):
        assert self._pubsub is not None
        for message in self._pubsub.listen():
            if message["type"] not in ("message", "pmessage"):
                continue
            data_raw = message.get("data")
            if not data_raw or data_raw == 1:
                continue
            try:
                payload = json.loads(data_raw)
                event_type = payload.get("event")
                text_id = payload.get("text_id")
                if event_type and text_id is not None:
                    self._notify_listeners(int(text_id), event_type, payload)
            except Exception as exc:
                logger.error(f"解析Redis事件失败: {exc}")

    def _notify_listeners(self, text_id: int, event_type: str, data: Dict[str, Any]):
        callbacks: List[Callable]
        with self._local_lock:
            callbacks = list(self._listeners.get(text_id, []))
        for cb in callbacks:
            try:
                cb(event_type, data)
            except Exception as exc:
                logger.error(f"SSE 回调失败: text_id={text_id}, err={exc}")

        # 同步 follower
        self._broadcast_to_followers(text_id, event_type, data)

    def _broadcast_to_followers(self, leader_text_id: int, event_type: str, data: Dict[str, Any]):
        followers = self.redis.smembers(self._followers_set(leader_text_id))
        if not followers:
            return
        for fid in followers:
            fid_int = int(fid)
            self.redis.publish(self._event_channel(fid_int), json.dumps({
                "event": event_type,
                **data,
                "text_id": fid_int
            }))

    def _generate_idempotency_key(self, text_content: str) -> str:
        return hashlib.sha256(text_content.encode("utf-8")).hexdigest()

    def _event_channel(self, text_id: int) -> str:
        return f"{self.namespace}:events:{text_id}"

    def _task_key(self, text_id) -> str:
        return f"{self.namespace}:task:{text_id}"

    def _active_set(self) -> str:
        return f"{self.namespace}:active"

    def _all_set(self) -> str:
        return f"{self.namespace}:all"

    def _idempotency_hash(self) -> str:
        return f"{self.namespace}:idempotency"

    def _stats_hash(self) -> str:
        return f"{self.namespace}:stats"

    def _followers_set(self, leader_text_id: int) -> str:
        return f"{self.namespace}:followers:{leader_text_id}"

    def _follow_parent_hash(self) -> str:
        return f"{self.namespace}:follow_parent"

    def _lock_name(self, key: str) -> str:
        return f"{self.namespace}:lock:{key}"


__all__ = ["RedisTaskMonitor"]
