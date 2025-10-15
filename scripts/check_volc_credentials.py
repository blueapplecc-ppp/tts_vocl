#!/usr/bin/env python3
"""火山引擎凭据快速巡检脚本（临时诊断用）"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_PARENT = PROJECT_ROOT.parent


def ensure_sys_path() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


ensure_sys_path()


def mask_secret(value: Optional[str], keep: int = 4) -> str:
    if not value:
        return "<空>"
    value = str(value)
    if len(value) <= keep * 2:
        return value[0] + "***" + value[-1]
    return value[:keep] + "***" + value[-keep:]


def load_external_config(config_path: Optional[Path]) -> Dict[str, Any]:
    if config_path is None:
        json_path = BASE_PARENT / "db_config.json"
        ini_path = BASE_PARENT / "db_config.ini"
    else:
        json_path = config_path
        ini_path = config_path

    cfg: Dict[str, Any] = {}

    if json_path.exists() and json_path.suffix == ".json":
        with open(json_path, "r", encoding="utf-8") as fp:
            cfg = json.load(fp)
        config_source = json_path
    elif ini_path.exists() and ini_path.suffix == ".ini":
        import configparser

        parser = configparser.ConfigParser()
        parser.read(ini_path, encoding="utf-8")
        for section in parser.sections():
            cfg[section] = {k: v for k, v in parser.items(section)}
        config_source = ini_path
    else:
        raise SystemExit("未找到配置文件，请指定 --config")

    def env_override(d: Dict[str, Any], prefix: str = "") -> None:
        for key, value in list(d.items()):
            env_key = (prefix + key).upper()
            if isinstance(value, dict):
                env_override(value, env_key + "_")
            else:
                env_val = os.getenv(env_key)
                if env_val is not None:
                    d[key] = env_val

    env_override(cfg)
    cfg["__source__"] = str(config_source)
    return cfg


def init_engine(mysql_cfg: Dict[str, Any]) -> Engine:
    host = mysql_cfg.get("HOST", "127.0.0.1")
    port = int(mysql_cfg.get("PORT", 3306))
    user = mysql_cfg.get("USER", "root")
    password = mysql_cfg.get("PASSWORD", "")
    db_name = mysql_cfg.get("DB", "tts_vocl")

    uri = f"mysql+pymysql://{user}:{password}@{host}:{port}/{db_name}?charset=utf8mb4"
    return create_engine(uri, future=True)


async def check_tts_credentials(app_id: str, access_token: str, endpoint: str) -> Dict[str, Any]:
    from app.tts_client import ping_auth_v3

    return await ping_auth_v3(app_id=app_id, access_token=access_token, endpoint=endpoint)


def fetch_usage(engine: Engine) -> Dict[str, Any]:
    usage = {
        "audio_count": 0,
        "total_duration": 0,
        "total_size": 0,
        "latest_audio": None,
        "text_characters": 0,
    }

    with engine.connect() as conn:
        audio_row = conn.execute(
            text(
                """
                SELECT COUNT(*) AS cnt,
                       COALESCE(SUM(duration_sec), 0) AS duration_sum,
                       COALESCE(SUM(file_size), 0) AS size_sum,
                       MAX(updated_at) AS latest_ts
                FROM tts_audios
                WHERE is_deleted = 0
                """
            )
        ).mappings().one()

        text_row = conn.execute(
            text(
                """
                SELECT COALESCE(SUM(char_count), 0) AS char_sum
                FROM tts_texts
                WHERE is_deleted = 0
                """
            )
        ).mappings().one()

    usage["audio_count"] = int(audio_row["cnt"] or 0)
    usage["total_duration"] = int(audio_row["duration_sum"] or 0)
    usage["total_size"] = int(audio_row["size_sum"] or 0)
    usage["latest_audio"] = audio_row["latest_ts"]
    usage["text_characters"] = int(text_row["char_sum"] or 0)
    return usage


def main() -> None:
    parser = argparse.ArgumentParser(description="火山引擎凭据状态与用量检查")
    parser.add_argument("--config", type=Path, help="指定配置文件路径（默认自动查找）", default=None)
    parser.add_argument("--endpoint", default="wss://openspeech.bytedance.com/api/v3/sami/podcasttts", help="自定义TTS端点")
    parser.add_argument("--show-secrets", action="store_true", help="直接输出凭据（默认脱敏显示）")
    args = parser.parse_args()

    cfg = load_external_config(args.config)
    volc_cfg = cfg.get("VOLC_TTS", {})
    mysql_cfg = cfg.get("MYSQL", {})

    app_id = volc_cfg.get("APP_ID", "")
    access_token = volc_cfg.get("ACCESS_TOKEN", "")
    secret_key = volc_cfg.get("SECRET_KEY", "")

    def display(value: Optional[str]) -> str:
        return value if args.show_secrets else mask_secret(value)

    print("=== 凭据信息 ===")
    print(f"配置来源: {cfg.get('__source__', '未知')}")
    print(f"APP_ID: {display(app_id)}")
    print(f"ACCESS_TOKEN: {display(access_token)}")
    print(f"SECRET_KEY: {display(secret_key)}")
    print(f"API_BASE: {volc_cfg.get('API_BASE', 'https://open.volcengineapi.com')}")

    print("\n=== 远端认证检查 ===")
    if not app_id or not access_token:
        print("凭据缺失，无法执行握手检查。")
    else:
        result = asyncio.run(check_tts_credentials(app_id, access_token, args.endpoint))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    print("\n=== 本地用量概览（数据库） ===")
    try:
        engine = init_engine(mysql_cfg)
        usage = fetch_usage(engine)
        print(json.dumps(usage, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:  # pylint: disable=broad-except
        print(f"数据库查询失败: {exc}")


if __name__ == "__main__":
    main()


