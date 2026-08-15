-- 游艺圈：数据侧只读查验账号（供平台方执行）
-- 执行位置：Navicat 连接 `youyiquan` 指向的正式库（历史记录地址 192.168.1.98:5432，
--   主机/端口以平台方 Navicat 连接配置现场值为准）
-- 用途：数据侧查验 staging 表结构与平台导入结果（只看不写）
-- 权限：仅 SELECT；会话默认只读，即使误用其他工具也无法写入
-- 写入权限：暂不开通；数据侧交付仍走 deliveries/ 文件包（总纲 §12.1）

CREATE ROLE data_reader LOGIN PASSWORD '<平台方自定强密码>';

-- 所有由该账号发起的会话默认只读（数据库层面双保险）
ALTER ROLE data_reader SET default_transaction_read_only TO on;

GRANT CONNECT ON DATABASE postgres TO data_reader;
GRANT USAGE ON SCHEMA public TO data_reader;

-- 只对"已存在"的表授权 SELECT，表不存在时自动跳过不报错
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['staging_manufacturer','manufacturer','product','accessory','category','document']
  LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=t) THEN
      EXECUTE format('GRANT SELECT ON public.%I TO data_reader', t);
    END IF;
  END LOOP;
END $$;

-- 验证（执行后应能查到该角色）：
-- SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'data_reader';
