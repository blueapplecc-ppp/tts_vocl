import os
import json
import configparser
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import threading
import time
from redis import Redis, ConnectionPool
from redis.exceptions import RedisError
from .config.logging_config import setup_logging, get_logger, add_memory_handler

engine = None
SessionLocal = None


def _load_external_config() -> dict:
    project_root = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(project_root, os.pardir))
    external_parent = os.path.abspath(os.path.join(parent_dir, os.pardir))

    cfg = {}
    json_path = os.path.join(external_parent, 'db_config.json')
    ini_path = os.path.join(external_parent, 'db_config.ini')

    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    elif os.path.exists(ini_path):
        parser = configparser.ConfigParser()
        parser.read(ini_path, encoding='utf-8')
        for section in parser.sections():
            cfg[section] = {k: v for k, v in parser.items(section)}

    def env_override(d: dict, prefix: str = ''):
        for k, v in list(d.items()):
            key = (prefix + k).upper()
            if isinstance(v, dict):
                env_override(v, key + '_')
            else:
                env_val = os.getenv(key)
                if env_val is not None:
                    d[k] = env_val

    env_override(cfg)
    return cfg


def _build_mysql_uri(mysql_cfg: dict) -> str:
    host = mysql_cfg.get('HOST', '127.0.0.1')
    port = int(mysql_cfg.get('PORT', 3306))
    user = mysql_cfg.get('USER', 'root')
    password = mysql_cfg.get('PASSWORD', '')
    db = mysql_cfg.get('DB', 'tts_vocl')
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"


def create_app() -> Flask:
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'), static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'))

    # 初始化日志（结构化 + 控制台 + 脱敏 + 内存缓冲）
    try:
        from .config.logging_config import setup_logging, add_memory_handler
        setup_logging(log_level=os.getenv('LOG_LEVEL', 'INFO'))
        add_memory_handler(logging.getLogger())
        # 提升协议与TTS客户端在诊断期的可见性（可通过环境变量覆盖）
        logging.getLogger('app.protocols').setLevel(os.getenv('LOG_LEVEL_PROTOCOLS', 'INFO'))
        logging.getLogger('app.tts_client').setLevel(os.getenv('LOG_LEVEL_TTS_CLIENT', 'INFO'))
        logging.getLogger('app.services.tts_service').setLevel(os.getenv('LOG_LEVEL_TTS_SERVICE', 'INFO'))
    except Exception:
        pass

    # 初始化日志系统
    setup_logging(log_dir="logs", log_level="INFO")
    logger = get_logger(__name__)
    add_memory_handler(logger)
    logger.info("应用初始化开始")

    cfg = _load_external_config()

    app.config['AUTH_ENABLED'] = bool(str(cfg.get('AUTH_ENABLED', 'false')).lower() == 'true')

    jwt_cfg = cfg.get('JWT', {})
    app.config['JWT_SECRET_KEY'] = jwt_cfg.get('SECRET', 'change-me')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = int(jwt_cfg.get('EXPIRES_MINUTES', 120)) * 60

    global engine, SessionLocal
    mysql_cfg = cfg.get('MYSQL', {})
    pool_size = int(mysql_cfg.get('POOL_SIZE', 10))
    pool_timeout = int(mysql_cfg.get('POOL_TIMEOUT', 5))
    pool_recycle = int(mysql_cfg.get('POOL_RECYCLE', 1800))

    engine = create_engine(
        _build_mysql_uri(mysql_cfg),
        pool_size=pool_size,
        pool_pre_ping=True,
        pool_recycle=pool_recycle,
        pool_timeout=pool_timeout,
        future=True,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    app.config['DATABASE_SESSION'] = SessionLocal

    # OSS client
    from .oss import OssClient
    oss_cfg = cfg.get('OSS', {})
    app.config['OSS_CLIENT'] = OssClient(
        endpoint=oss_cfg.get('ENDPOINT', ''),
        bucket=oss_cfg.get('BUCKET', ''),
        access_key_id=oss_cfg.get('ACCESS_KEY_ID', ''),
        access_key_secret=oss_cfg.get('ACCESS_KEY_SECRET', ''),
    )

    # TTS client
    from .tts_client import VolcTtsClient
    from .services import TTSService, TaskService, AudioService
    from .services.task_service import configure_tts_concurrency
    from .infrastructure.monitoring import InMemoryTaskMonitor, TaskMonitorProtocol
    from .infrastructure.redis_monitor import RedisTaskMonitor
    from .config.settings import TTSSettings, PublicSettings, RedisSettings
    
    # TTS配置
    tts_settings = TTSSettings.from_config(cfg)
    tts_client = VolcTtsClient(
        app_id=tts_settings.app_id,
        access_token=tts_settings.access_token,
        secret_key=tts_settings.secret_key,
        api_base=tts_settings.api_base
    )
    
    # 创建服务层
    tts_service = TTSService(tts_client, {
        'available_speakers': tts_settings.available_speakers,
        'max_text_length': tts_settings.max_text_length,
        'max_retries': tts_settings.max_retries,
        'retry_delay': tts_settings.retry_delay,
    })
    
    # Redis 监控
    redis_client = None
    redis_settings = RedisSettings.from_config(cfg)
    monitor: TaskMonitorProtocol

    if redis_settings.enabled:
        try:
            connection_pool = ConnectionPool.from_url(
                redis_settings.url,
                max_connections=redis_settings.max_connections,
                decode_responses=True
            )
            redis_client = Redis(connection_pool=connection_pool)
            redis_client.ping()
            monitor = RedisTaskMonitor(redis_client)
            app.config['MONITOR_MODE'] = 'redis'
        except RedisError as exc:
            logger.warning(f"Redis 不可用，回退到内存模式: {exc}")
            redis_client = None
            monitor = InMemoryTaskMonitor()
            app.config['MONITOR_MODE'] = 'memory'
    else:
        monitor = InMemoryTaskMonitor()
        app.config['MONITOR_MODE'] = 'memory'

    system_cfg = cfg.get('SYSTEM', {})
    global_limit = int(system_cfg.get('max_concurrent_tasks', 8))
    per_worker_limit = int(system_cfg.get('per_worker_tts_limit', max(1, min(global_limit, 2))))
    configure_tts_concurrency(
        redis_client if app.config['MONITOR_MODE'] == 'redis' else None,
        global_limit=global_limit,
        fallback_limit=per_worker_limit
    )
    # 任务服务
    task_service = TaskService(tts_service, app.config['OSS_CLIENT'], monitor)
    
    # 音频服务
    audio_service = AudioService(app.config['OSS_CLIENT'])
    
    # 注册到应用上下文
    app.config['TTS_CLIENT'] = tts_client  # 保持向后兼容
    app.config['TTS_SERVICE'] = tts_service
    app.config['TASK_SERVICE'] = task_service
    app.config['AUDIO_SERVICE'] = audio_service
    app.config['MONITOR'] = monitor
    app.config['REDIS'] = redis_client
    
    # 公开配置（可暴露给前端）
    public_settings = PublicSettings.from_config(cfg)
    app.config['PUBLIC_CONFIG'] = public_settings


    from .views import bp as main_bp
    app.register_blueprint(main_bp)

    # 后台超时检查线程，避免任务卡住无终态
    def _timeout_watcher(mon: TaskMonitorProtocol, interval: int = 30):
        while True:
            try:
                mon.check_timeouts()
            except Exception:
                pass
            time.sleep(interval)

    try:
        is_main = os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug
    except Exception:
        is_main = True
    if is_main:
        watcher = threading.Thread(target=_timeout_watcher, args=(monitor,), daemon=True)
        watcher.start()

    return app
