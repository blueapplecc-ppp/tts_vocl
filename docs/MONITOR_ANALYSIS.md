# 系统监控失效问题分析报告

**作者：蘑菇🍄**  
**日期：2025-10-14**

## 一、核心问题

系统监控页面经常无法有效监控任务状态，主要表现为：
1. **监控数据为空**：页面显示"暂无活跃任务"，但实际有任务在运行
2. **统计数据不准**：总任务数、成功率等指标与实际不符
3. **历史任务丢失**：服务重启后所有监控数据清空

## 二、根因分析

### 2.1 核心架构缺陷

#### 问题1：内存存储导致数据易丢失
**位置**: `app/infrastructure/monitoring.py:39-41`
```python
self.stats = defaultdict(int)
self.tasks: Dict[int, TaskInfo] = {}  # text_id -> TaskInfo
self.idempotency_map: Dict[str, int] = {}
```

**缺陷**：
- 所有监控数据存储在内存字典中
- **服务重启即丢失所有数据**
- 无持久化机制，无法恢复历史状态

**影响**：
- Gunicorn多worker环境下，每个worker维护独立的Monitor实例
- 重启服务后`total_tasks`归零，成功率计算错误
- 无法追溯历史任务执行情况

#### 问题2：任务状态仅保留活跃任务
**位置**: `app/infrastructure/monitoring.py:302-318`
```python
def get_stats(self) -> Dict[str, Any]:
    with self.lock:
        active_tasks = sum(1 for t in self.tasks.values() 
                          if t.status == TaskStatus.PROCESSING)
        total_tasks = len(self.tasks)
```

**缺陷**：
- `total_tasks = len(self.tasks)` 仅统计当前内存中的任务
- **已完成/失败的任务未从`self.tasks`移除**，导致内存无限增长
- 但实际上这个设计也意味着历史任务会一直留在内存中

**矛盾点**：
- 设计上任务完成后仍保留在`self.tasks`中（用于查询状态）
- 但无清理机制，长期运行会导致内存泄漏
- 重启后又全部丢失，无法利用历史数据

#### 问题3：前端筛选依赖内存状态
**位置**: `templates/text_library.html:269-273`
```javascript
// 任务状态前端筛选
const isProcessing = row.querySelector('.animate-spin') !== null;
const isFailed = row.dataset.taskStatus === 'failed' || 
                 row.dataset.taskStatus === 'timeout';
```

**缺陷**：
- 前端的"仅失败/超时"筛选依赖`task_status_map`
- `task_status_map`来自Monitor内存状态
- **任务完成后Monitor不清理，但也不持久化，导致：**
  - 短期内可查（任务还在内存中）
  - 重启后失效（内存清空）
  - 长期运行内存溢出

### 2.2 数据一致性问题

#### 问题4：统计数据与实际脱节
**位置**: `app/infrastructure/monitoring.py:162-163, 192-193, 219-220`
```python
# start_task
self.stats['tasks_started'] += 1

# complete_task  
self.stats['tasks_completed'] += 1
self.stats['total_duration'] += duration

# fail_task
self.stats['tasks_failed'] += 1
```

**缺陷**：
- 统计计数器独立维护，不校验一致性
- 可能出现：`tasks_started < tasks_completed + tasks_failed`
- 服务重启后所有计数器归零，但数据库中有历史任务

**示例场景**：
```
1. 服务启动前已有100个任务完成
2. 重启后 total_tasks=0, tasks_completed=0
3. 新增1个任务完成 → total_tasks=1, tasks_completed=1
4. 成功率=100%（实际应考虑历史数据）
```

### 2.3 并发安全问题

#### 问题5：Gunicorn多worker不共享状态
**位置**: `app/__init__.py:56` + Gunicorn配置
```bash
gunicorn -w 4 -b 0.0.0.0:8082
```

**缺陷**：
- 4个worker各自创建独立的Monitor实例
- Worker A处理的任务，Worker B的Monitor无感知
- 监控API随机分发到某个worker，看到的是**局部状态**

**实际影响**：
- 用户访问`/api/monitor/stats`可能命中任何worker
- 每次看到的`active_tasks`不同（取决于哪个worker处理了任务）
- `total_tasks`是单个worker的局部计数，不是全局统计

#### 问题6：锁的作用域仅限单worker
**位置**: `app/infrastructure/monitoring.py:46`
```python
self.lock = threading.RLock()
```

**缺陷**：
- `RLock`仅保护单进程内的线程安全
- 无法跨worker进程同步
- 多个worker同时修改各自的Monitor，数据彻底割裂

### 2.4 API设计缺陷

#### 问题7：max_concurrent读取不准确
**位置**: `app/views.py:563-564`
```python
from .services.task_service import _TTS_CONCURRENCY_SEMA
max_concurrent = _TTS_CONCURRENCY_SEMA._value
```

**缺陷**：
- `_value`是Semaphore的初始值，不是当前可用值
- 正确应该是：`max_concurrent = _TTS_CONCURRENCY_SEMA._initial_value`
- 但这也无法反映实时并发上限变化

#### 问题8：缺少异常任务清理机制
**位置**: `app/infrastructure/monitoring.py:293-300`
```python
def check_timeouts(self):
    """检查超时任务"""
    current_time = time.time()
    with self.lock:
        for text_id, task_info in list(self.tasks.items()):
            if (task_info.status == TaskStatus.PROCESSING and 
                current_time - task_info.start_time > self.timeout_seconds):
                self.timeout_task(text_id)
```

**缺陷**：
- `check_timeouts`方法定义了，但**从未被调用**
- 超时任务永远保持`PROCESSING`状态
- 占用并发槽位，导致真实并发数低于配置值

## 三、问题汇总表

| 问题编号 | 问题描述 | 严重程度 | 影响范围 |
|---------|---------|---------|---------|
| P1 | 内存存储无持久化，重启丢失所有监控数据 | 🔴 严重 | 全局 |
| P2 | 多worker状态不共享，监控数据割裂 | 🔴 严重 | 全局 |
| P3 | 任务完成后不清理，内存无限增长 | 🟠 中等 | 长期运行 |
| P4 | 统计数据与数据库脱节，重启后归零 | 🟠 中等 | 重启时 |
| P5 | 超时检查机制未启用 | 🟠 中等 | 长任务 |
| P6 | 前端筛选依赖内存状态，重启后失效 | 🟡 轻微 | 用户体验 |
| P7 | max_concurrent读取错误 | 🟡 轻微 | 显示准确性 |

## 四、解决方案建议

### 4.1 短期改进（MVP）

#### 方案1：从数据库实时统计
```python
def get_stats(self) -> Dict[str, Any]:
    """从数据库获取统计信息，而非依赖内存"""
    with get_session() as s:
        # 总任务数
        total_tasks = s.query(TtsText).filter(TtsText.is_deleted == 0).count()
        
        # 成功任务数（有音频记录）
        completed = s.query(TtsAudio).filter(
            TtsAudio.is_deleted == 0,
            TtsAudio.file_size >= 5000  # 有效音频
        ).distinct(TtsAudio.text_id).count()
        
        # 内存中活跃任务
        active_tasks = sum(1 for t in self.tasks.values() 
                          if t.status == TaskStatus.PROCESSING)
        
        # 成功率
        success_rate = (completed / total_tasks * 100) if total_tasks > 0 else 0
        
        return {
            'active_tasks': active_tasks,
            'total_tasks': total_tasks,
            'tasks_completed': completed,
            'success_rate': success_rate
        }
```

**优点**：
- 数据库为单一数据源，跨worker一致
- 重启后统计准确
- 无需迁移现有架构

**缺点**：
- 每次查询需访问数据库
- 平均耗时等指标需额外计算

#### 方案2：启用超时检查后台线程
```python
# app/__init__.py
def create_app():
    monitor = TaskMonitor()
    
    # 启动超时检查线程
    def timeout_checker():
        while True:
            time.sleep(60)  # 每分钟检查一次
            monitor.check_timeouts()
    
    import threading
    t = threading.Thread(target=timeout_checker, daemon=True)
    t.start()
    
    return app
```

#### 方案3：清理已完成任务（防止内存泄漏）
```python
def complete_task(self, text_id: int, audio_url: str, filename: Optional[str] = None):
    """完成任务"""
    with self.lock:
        # ... 原有逻辑 ...
        
        # 🆕 完成后从内存移除（保留统计）
        del self.tasks[text_id]
        # 但保留幂等键一段时间（防止重复提交）
        # idempotency_map可设置TTL或周期清理
```

**权衡**：
- 移除后无法再通过`get_task_status(text_id)`查询
- 需结合数据库查询补充历史状态

### 4.2 长期架构改进

#### 方案4：使用Redis作为共享存储
```python
import redis

class TaskMonitor:
    def __init__(self):
        self.redis = redis.Redis(host='localhost', port=6379, db=0)
    
    def start_task(self, text_id: int, text_content: str):
        key = f"task:{text_id}"
        self.redis.hset(key, mapping={
            'status': 'processing',
            'start_time': time.time(),
            'content_hash': hashlib.sha256(text_content.encode()).hexdigest()
        })
        self.redis.expire(key, 86400)  # 24小时过期
```

**优点**：
- 跨worker进程共享状态
- 重启后数据可恢复
- 支持TTL自动清理

**缺点**：
- 引入新依赖（Redis）
- 需改造现有代码

#### 方案5：任务状态写入数据库
在`tts_audios`表新增字段：
```sql
ALTER TABLE tts_audios ADD COLUMN task_status VARCHAR(20);
ALTER TABLE tts_audios ADD COLUMN start_time TIMESTAMP;
ALTER TABLE tts_audios ADD COLUMN completed_time TIMESTAMP;
ALTER TABLE tts_audios ADD COLUMN error_message TEXT;
```

**优点**：
- 数据持久化
- 无需额外存储
- 便于历史查询

**缺点**：
- 数据库写入频繁
- 需迁移现有逻辑

## 五、推荐实施路径

### 阶段1：立即修复（1天）
1. ✅ 修改`get_stats()`从数据库统计 → 解决P1, P4
2. ✅ 启用超时检查后台线程 → 解决P5
3. ✅ 修正`max_concurrent`读取方式 → 解决P7

### 阶段2：短期优化（3天）
1. ✅ 完成任务后移除内存记录 → 解决P3
2. ✅ 为前端筛选提供数据库查询接口 → 解决P6
3. ✅ 添加Monitor状态导出/恢复机制（可选）

### 阶段3：长期架构（1-2周）
1. 🔄 评估Redis引入可行性
2. 🔄 设计任务状态数据库表结构
3. 🔄 逐步迁移到Redis/数据库存储 → 解决P2

## 六、注意事项

1. **向后兼容**：改造时保留现有API接口，避免破坏前端
2. **渐进式升级**：先修复统计逻辑，再考虑存储迁移
3. **监控监控**：添加Monitor自身健康检查，防止静默失败
4. **文档更新**：修改后更新API文档和部署文档

---

**下一步行动**：
建议优先实施阶段1的3项修复，快速解决当前监控失效问题，再规划长期架构改进。

