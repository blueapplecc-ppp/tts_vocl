-- schema for TTS_VOCL (MySQL 8+)
-- charset: utf8mb4, collation: utf8mb4_0900_ai_ci

CREATE TABLE IF NOT EXISTS tts_users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  unified_user_id VARCHAR(64) NOT NULL,
  name VARCHAR(128) NOT NULL,
  email VARCHAR(255) NULL,
  avatar_url VARCHAR(512) NULL,
  platform VARCHAR(32) NOT NULL,
  platform_user_id VARCHAR(128) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uq_email (email),
  UNIQUE KEY uq_platform_user (platform, platform_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tts_texts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  filename VARCHAR(255) NOT NULL,
  title VARCHAR(255) NOT NULL,
  content LONGTEXT NOT NULL,
  char_count INT NOT NULL,
  oss_object_key VARCHAR(512) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  CONSTRAINT fk_texts_user FOREIGN KEY (user_id) REFERENCES tts_users(id),
  KEY idx_texts_user_created (user_id, created_at),
  KEY idx_texts_created (created_at),
  KEY idx_texts_title (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tts_audios (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  text_id BIGINT NOT NULL,
  user_id BIGINT NOT NULL,
  filename VARCHAR(255) NOT NULL,
  oss_object_key VARCHAR(512) NOT NULL,
  duration_sec INT NULL,
  file_size BIGINT NULL,
  version_num INT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  CONSTRAINT fk_audios_text FOREIGN KEY (text_id) REFERENCES tts_texts(id),
  CONSTRAINT fk_audios_user FOREIGN KEY (user_id) REFERENCES tts_users(id),
  UNIQUE KEY uq_audio_version (text_id, version_num),
  KEY idx_audios_created (created_at),
  KEY idx_audios_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tts_downloads (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  audio_id BIGINT NOT NULL,
  user_id BIGINT NULL,
  downloaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ip_address VARCHAR(64) NULL,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  CONSTRAINT fk_downloads_audio FOREIGN KEY (audio_id) REFERENCES tts_audios(id),
  CONSTRAINT fk_downloads_user FOREIGN KEY (user_id) REFERENCES tts_users(id),
  KEY idx_downloads_audio_time (audio_id, downloaded_at),
  KEY idx_downloads_user_time (user_id, downloaded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS tts_system_config (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  config_key VARCHAR(128) NOT NULL,
  config_value TEXT NULL,
  description VARCHAR(512) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  is_deleted TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uq_config_key (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
