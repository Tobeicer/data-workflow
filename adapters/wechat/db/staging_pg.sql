-- 微信来源 staging 表（PostgreSQL）
-- 状态：待平台确认连接与字段基线后执行；仅建 staging 表，不写正式业务表。
-- 命名与 docs/游艺圈数据工作流总纲.md Phase H H2 一致。

BEGIN;

CREATE TABLE IF NOT EXISTS wechat_msg (
  id BIGSERIAL PRIMARY KEY,
  chat_name TEXT NOT NULL,
  local_id BIGINT NOT NULL,
  server_id BIGINT,
  local_type BIGINT,
  type_name TEXT,
  create_time BIGINT,
  sender_id TEXT,
  text TEXT,
  xml_fields JSONB,
  source_raw TEXT,
  raw TEXT,
  batch TEXT,
  loaded_at BIGINT,
  CONSTRAINT uq_wechat_msg UNIQUE (chat_name, local_id, create_time)
);
CREATE INDEX IF NOT EXISTS idx_wechat_msg_time ON wechat_msg (create_time);

CREATE TABLE IF NOT EXISTS wechat_moment (
  id BIGSERIAL PRIMARY KEY,
  moment_id TEXT UNIQUE,
  user_name TEXT,
  create_time BIGINT,
  content_desc TEXT,
  location TEXT,
  media JSONB,
  batch TEXT,
  loaded_at BIGINT
);

CREATE TABLE IF NOT EXISTS wechat_contact (
  id BIGSERIAL PRIMARY KEY,
  user_name TEXT UNIQUE,
  sender_id BIGINT,
  is_session BIGINT,
  nick_name TEXT,
  remark TEXT,
  is_group BIGINT,
  batch TEXT,
  loaded_at BIGINT
);

CREATE TABLE IF NOT EXISTS sync_watermark (
  source TEXT PRIMARY KEY,
  watermark TEXT,
  updated_at BIGINT
);

COMMIT;
