# TTS火山版 (TTS_VOCL)

一个文本到音频的后台平台：提交文本 → 火山引擎 TTS v3 异步生成音频 → 文本/音频保存至阿里云 OSS（公开读）并可在线播放/下载。

## 技术栈
- Flask + SQLAlchemy + PyMySQL (MySQL)
- Tailwind + Jinja2 (前端模板)
- 阿里云 OSS (公开读)
- 可选鉴权：Google OAuth、飞书 OAuth（可关闭）

## 运行要求
- Python 3.10+
- 已创建 MySQL 数据库与账号（最小权限）
- 已创建阿里云 OSS Bucket（公开读）

## 快速开始
1. 创建虚拟环境并安装依赖
```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境（每次启动项目前必须执行）
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

2. 准备外层父目录配置（禁止硬编码）
- 在项目外层父目录（即本项目上一级目录）放置配置文件：`db_config.json` 或 `db_config.ini`
- 环境变量可覆盖同名配置键（规则：用大写+下划线层级，如 `MYSQL_HOST`, `OSS_BUCKET`, `AUTH_ENABLED`）

最低配置示例（db_config.json）：
```
{
  "AUTH_ENABLED": false,
  "MYSQL": {
    "HOST": "127.0.0.1",
    "PORT": 3306,
    "USER": "tts_user",
    "PASSWORD": "******",
    "DB": "tts_vocl",
    "POOL_SIZE": 10,
    "POOL_TIMEOUT": 5,
    "POOL_RECYCLE": 1800
  },
  "OSS": {
    "ENDPOINT": "https://oss-cn-xxx.aliyuncs.com",
    "ACCESS_KEY_ID": "AKIxxxxxxxx",
    "ACCESS_KEY_SECRET": "xxxxxxxx",
    "BUCKET": "tts-public-read"
  },
  "JWT": {
    "SECRET": "change-me",
    "EXPIRES_MINUTES": 120
  },
  "VOLC_TTS": {
    "APP_ID": "your_app_id",
    "ACCESS_TOKEN": "your_access_token",
    "SECRET_KEY": "your_secret_key",
    "API_BASE": "https://open.volcengineapi.com"
  },
  "OAUTH": {
    "GOOGLE": {"CLIENT_ID": "...", "CLIENT_SECRET": "...", "REDIRECT_URI": "..."},
    "FEISHU": {"APP_ID": "...", "APP_SECRET": "...", "REDIRECT_URI": "..."}
  },
  "PROXY": {"USE_SYSTEM": true}
}
```

3. 初始化数据库
- 使用 `schema.sql` 在目标库中执行建表和索引

4. 运行
```bash
# 确保虚拟环境已激活
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 设置开发环境
export FLASK_ENV=development

# 启动应用
python run_refactored_app.py  # 默认监听 8081
```

**重要提醒：每次启动项目前都必须先激活虚拟环境！**

## 部署（无 sudo 环境）
- 参考根目录文档：`DEPLOY_NO_SUDO.md`
- 一键脚本：`docs/scripts/deploy.sh`（在项目根目录执行，生成 `./start.sh`、`./stop.sh`、`./restart.sh`、`./health.sh`）

## 配置键说明（摘要）
- `AUTH_ENABLED`: 是否启用鉴权（布尔）
- `MYSQL`: `HOST`, `PORT`, `USER`, `PASSWORD`, `DB`, `POOL_SIZE`, `POOL_TIMEOUT`, `POOL_RECYCLE`
- `OSS`: `ENDPOINT`, `BUCKET`, `ACCESS_KEY_ID`, `ACCESS_KEY_SECRET`
- `JWT`: `SECRET`, `EXPIRES_MINUTES`
- `VOLC_TTS`: `APP_ID`, `ACCESS_TOKEN`, `SECRET_KEY`, `API_BASE`
- `OAUTH`: `GOOGLE`, `FEISHU`（可后续接入；`AUTH_ENABLED=false` 开发期可关闭）
- 代理：遵循系统环境变量 `http_proxy`/`https_proxy`/`all_proxy`

## 最小端到端测试清单（E2E）
1. 启动应用：访问 `http://127.0.0.1:8081/`
2. 上传文本页面：上传 `.txt`（≤5MB），默认标题为文件名（可编辑标题与文本）
3. 点击“生成音频”：
   - 文本应上传至 OSS（公开读）
   - `tts_texts` 新增记录
   - 后台异步任务调用 TTS v3，音频文件上传至 OSS（公开读），`tts_audios` 新增记录
4. 文本资源库（首页）：
   - 顶部列表应显示新文本（默认时间降序）
   - 右侧应出现此文本的音频播放器和“下载”按钮（公开读 URL）
   - 点击标题可在下半部分看到只读全文预览
5. 音频资源库：
   - 列表每页40条，支持搜索与排序；音频可播放与下载（公开读 URL）

## 关键约束（摘要）
- 表名前缀统一 `tts_`，核心表含 `created_at`/`updated_at` 与 `is_deleted`
- 外部请求遵循系统代理 `http_proxy/https_proxy/all_proxy`
- 鉴权可开关（`AUTH_ENABLED=false` 时以开发用户运行）
- 列表分页 40 条，键集/游标分页优先，避免 `SELECT *`

## 目录结构（后续补充）
- `app/` Flask 应用代码
  - `__init__.py`（配置加载、DB与客户端初始化、蓝图注册）
  - `models.py`（SQLAlchemy ORM 模型）
  - `views.py`（路由与页面）
  - `auth.py`（鉴权开关与开发模式用户注入）
  - `oss.py`（OSS 封装）
  - `tts_client.py`（火山引擎 TTS v3 客户端与命名规则）
  - `tasks.py`（有界线程池与TTS后台任务）
- `templates/`（Jinja2 模板：layout/text_library/audio_library/upload_text）
- `static/`（静态资源）

## 迁移与运维建议
- 使用 Alembic 维护迁移脚本（向前兼容：加字段→双写→回填→切换→清理）
- 监控：慢查询、连接池、QPS/延迟/错误率、锁等待、容量与碎片
- 备份与恢复演练：定义 RPO/RTO（如 RPO≤24h，RTO≤4h）
- 异步队列：有界队列与线程池利用率监控，失败重试与超时设置
