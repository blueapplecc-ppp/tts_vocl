# Redis 任务监控改造开发计划

## 背景
- 现有 `TaskMonitor` 为每个 Gunicorn worker 启动时各自实例化，状态保存在进程内存。
- 多 worker/多实例时，幂等判断、任务状态查询与并发配额会出现不一致或丢失。
- 引入 Redis 作为中心化状态存储与事件分发，实现跨进程共享以及后续扩展能力。

## 目标
1. 提供 Redis 版本的任务监控，实现：
   - 任务状态/幂等键/统计信息全局一致。
   - Redis 发布订阅保障 SSE/轮询事件跨 worker 分发。
2. 替换 `_TTS_CONCURRENCY_SEMA` 为 Redis 分布式信号量，保证真实的全局并发上限。
3. 保留内存模式作为回退方案（Redis 不可用时自动降级）。
4. 最小化对现有 API 和前端的侵入，保持接口兼容。

## 范围
- 后端
  - `requirements.txt` 增加 `redis`。
  - `app/config/settings.py` 新增 Redis 配置模型。
  - `app/__init__.py` 初始化 Redis 连接并注入 `RedisTaskMonitor`，失败时回退内存实现。
  - 新建 `app/infrastructure/redis_monitor.py`，封装 Redis 版本 TaskMonitor。
  - 调整原有 `TaskMonitor` 为 `InMemoryTaskMonitor` 并抽象接口。
  - 在 `app/services/task_service.py` 中替换并发控制实现。
  - 调整 SSE (`/api/task/stream/<id>`) 与监控接口以适配 Redis 事件。
- 前端
  - 若需：确保 `templates/monitor.html` 轮询结果正确渲染，无需大改。
- 文档
  - 当前计划 (`docs/redis_task_monitor_plan.md`)。
  - 更新 README/部署说明（待开发结束后补充）。

## 实施步骤
1. **准备阶段**
   - [x] 安装 Redis Python 客户端，确认生产环境 Redis 可用（已验证 `redis-cli ping`）。
   - [x] 评估现有 `TaskMonitor` 调用点，确保接口兼容。
2. **配置与依赖**
   - [x] 修改 `requirements.txt` 增加 `redis==5.x`。
   - [x] 在 `app/config/settings.py` 添加 `RedisSettings` 并读取外部配置。
   - [x] 在 `app/__init__.py` 中创建 Redis 连接池，注入 `app.config['REDIS']`。
3. **Redis TaskMonitor**
   - [x] 新建 `RedisTaskMonitor` 类：
        - `start_task` 结合分布式锁 + Redis 脚本保证幂等。
        - 任务状态存储在 Redis 哈希结构，活跃集合使用 `SADD/SREM`。
        - `complete_task`/`fail_task` 发布事件到 `pub/sub` 频道。
        - `get_stats` 聚合 Redis 数据生成指标。
   - [x] 将原 `TaskMonitor` 重命名为 `InMemoryTaskMonitor` 并实现公共接口。
   - [x] 在 `create_app` 中根据 Redis 连通性选择 monitor 实现。
4. **事件推送与 SSE**
   - [x] `/api/task/status/<id>` 与 `/api/monitor/stats` 通过 Redis-backed monitor 读取全局状态。
   - [x] `/api/task/stream/<id>` 消费 Redis `pubsub` 事件，确保跨 worker 推送。
   - [x] 新增队列阶段字段，区分 `queued` / `running` / `done`，监控页面展示排队中的任务量。
5. **分布式信号量**
   - [x] 实现基于 Redis Sorted Set 的分布式信号量，防止并发突增。
   - [x] 在 `TaskService` 中注入 Redis 信号量实例。
6. **测试与验证**
   - [ ] 在开发环境模拟多 worker（Gunicorn `-w 4`）验证任务状态一致。
   - [ ] 灰度测试：在低峰期切换至 Redis 模式观察监控页。
   - [ ] 验证内存回退：停 Redis 服务->重启应用->流程仍可运行（但监控受限）。
7. **上线准备**
   - [ ] 更新部署文档：新增 Redis 配置说明、回退策略。
   - [ ] 编写问题排查指南：Redis 不可用、连接超时、信号量泄漏等。
   - [ ] 与运维确认监控指标（Redis key 数、任务成功率、并发使用率）。

## 风险与缓解
- **Redis 不可用**：自动回退内存模式；在日志中输出告警。
- **信号量泄漏**：Lua 脚本与 `finally` 块确保释放；设置 TTL 防止进程崩溃后残留。
- **事件堆积**：`pub/sub` 无持久化；关键事件（完成/失败）同时写入状态哈希，前端轮询可兜底。
- **数据一致性**：所有写操作封装在 Lua 脚本或事务中，避免并发竞态。

## 后续扩展
- 引入 Redis Streams 支持任务重放与历史记录。
- 将监控数据暴露给 Prometheus（通过 Exporter 或自定义指标）。
- 扩展到多实例部署，利用 Redis 进行跨机协调。
- 视需要将任务执行迁移到 Celery/任务队列，Redis 作为 broker/backing store。
