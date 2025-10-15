# TTS火山版 (TTS_VOCL) 开发文档

## 项目概述

TTS火山版是一个文本到音频的后台管理平台，允许用户上传文本文件，使用火山引擎TTS v3服务生成多音色对话音频，并将生成的音频和文本保存到公共资源库中供所有用户浏览和下载。

## 核心功能

### 1. 文本资源库（首页）
- **布局**：经典后台布局，左侧导航，右侧工作区
- **功能**：
  - 每页40条记录，支持分页
  - 模糊搜索（标题/上传者）
  - 时间排序（默认降序）
  - 文本预览（只读）
  - 音频播放和下载

### 2. 音频资源库
- **功能**：
  - 每页40条记录，支持分页
  - 模糊搜索（标题/生成者）
  - 时间排序（默认降序）
  - 在线播放和下载

### 3. 上传文本
- **功能**：
  - 支持拖拽上传.txt文件（≤5MB）
  - 文件内容预览和编辑
  - 自动生成音频
  - 文本锁定机制

## 技术架构

### 后端技术栈
- **框架**：Flask 3.0.3
- **数据库**：MySQL 8+ (utf8mb4)
- **ORM**：SQLAlchemy 2.0.32
- **异步任务**：ThreadPoolExecutor + BoundedSemaphore
- **存储**：阿里云OSS（公开读）
- **TTS服务**：火山引擎TTS v3

### 前端技术栈
- **UI框架**：Tailwind CSS
- **模板引擎**：Jinja2
- **交互**：原生JavaScript

### 数据库设计
所有表名以`tts_`为前缀：

- `tts_users`：用户信息
- `tts_texts`：文本内容
- `tts_audios`：音频信息
- `tts_downloads`：下载记录
- `tts_system_config`：系统配置

## 项目结构

```
tts_vocl/
├── app/                    # Flask应用核心代码
│   ├── __init__.py        # 应用工厂和配置加载
│   ├── models.py          # SQLAlchemy数据模型
│   ├── views.py           # 路由和视图函数
│   ├── auth.py            # 认证和用户管理
│   ├── oss.py             # 阿里云OSS客户端
│   ├── tts_client.py      # 火山引擎TTS客户端
│   └── tasks.py           # 异步任务处理
├── templates/             # Jinja2模板
│   ├── layout.html        # 基础布局
│   ├── text_library.html  # 文本资源库
│   ├── audio_library.html # 音频资源库
│   └── upload_text.html   # 上传文本
├── docs/                  # 项目文档
├── requirements.txt       # Python依赖
├── schema.sql            # 数据库结构
├── dev_server.py # 开发环境启动脚本
└── README.md             # 项目说明
```

## 配置管理

### 配置文件位置
配置文件位于项目外层父目录：`/Users/gold/codes/db_config.json`

### 配置项说明
```json
{
  "AUTH_ENABLED": false,           // 鉴权开关
  "MYSQL": {                       // 数据库配置
    "HOST": "127.0.0.1",
    "PORT": 3306,
    "USER": "root",
    "PASSWORD": "***",
    "DB": "tts_vocl"
  },
  "OSS": {                         // 阿里云OSS配置
    "ENDPOINT": "https://oss-cn-shanghai.aliyuncs.com",
    "BUCKET": "ai-books-audios",
    "ACCESS_KEY_ID": "***",
    "ACCESS_KEY_SECRET": "***"
  },
  "VOLC_TTS": {                    // 火山引擎TTS配置
    "APP_ID": "***",
    "ACCESS_TOKEN": "***",
    "SECRET_KEY": "***",
    "API_BASE": "https://open.volcengineapi.com"
  }
}
```

## 核心业务流程

### 1. 文件上传流程
```
用户拖拽文件 → JavaScript处理 → 文件预览 → 用户编辑 → 提交表单
```

### 2. TTS生成流程
```
文本保存 → 异步任务提交 → TTS合成 → OSS上传 → 数据库记录
```

### 3. 音频命名规则
- 格式：`{原文件名}_{长度标识}_{版本}.mp3`
- 长度标识：字数>4000为"长"，否则也为"长"
- 版本：v01-v99
- 示例：`刻意练习_长_v01.mp3`

## 开发规范

### 代码规范
1. **数据库**：所有表名以`tts_`前缀
2. **软删除**：使用`is_deleted`字段
3. **时间戳**：`created_at`和`updated_at`
4. **错误处理**：详细的日志记录
5. **异步任务**：使用有界队列

### 安全规范
1. **配置管理**：禁止硬编码敏感信息
2. **输入验证**：文件类型和大小限制
3. **SQL注入**：使用参数化查询
4. **代理支持**：遵循系统代理设置

## 部署说明

### 环境要求
- Python 3.10+
- MySQL 8+
- 阿里云OSS账户
- 火山引擎TTS服务

### 部署步骤
1. 创建虚拟环境：`python -m venv .venv`
2. 激活环境：`source .venv/bin/activate`
3. 安装依赖：`pip install -r requirements.txt`
4. 配置数据库：执行`schema.sql`
5. 配置外部文件：`db_config.json`
6. 启动服务：
   - 开发环境：`python dev_server.py`
   - 生产环境：`./start.sh`（仅在服务未运行时启动）
   - 重启服务：`./restart.sh`
   - 停止服务：`./stop.sh`
   - 健康检查：`./health.sh`

## 监控和维护

### 日志监控
- 应用日志：Flask开发服务器输出
- 数据库日志：MySQL慢查询日志
- 任务日志：异步任务执行状态

### 性能优化
- 数据库索引：基于查询模式优化
- 连接池：合理配置连接数
- 缓存策略：可考虑Redis缓存

### 备份策略
- 数据库备份：定期全量备份
- 文件备份：OSS自动备份
- 配置备份：版本控制管理

## 扩展计划

### 短期优化
1. 真实TTS API集成
2. 音频时长解析
3. 用户通知机制
4. 失败重试机制

### 长期规划
1. 多语言支持
2. 批量处理
3. 用户权限管理
4. 数据分析面板

## 故障排除

### 常见问题
1. **配置文件错误**：检查JSON格式和路径
2. **数据库连接失败**：验证MySQL服务状态
3. **OSS上传失败**：检查网络和凭据
4. **TTS任务失败**：查看异步任务日志

### 调试工具
- Flask调试模式：`FLASK_ENV=development`
- 数据库查询：直接MySQL客户端
- 日志查看：终端输出和文件日志

## 联系信息

- 项目维护者：[开发者信息]
- 技术支持：[联系方式]
- 问题反馈：[Issue链接]

---

*最后更新：2025-09-03*
*版本：v1.0.0*
