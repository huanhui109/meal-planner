-- 建库与应用账号 (以 root 执行)
--
-- 本脚本不含任何真实密码。密码从环境变量注入, 由 shell 做占位替换后执行,
-- 这样明文凭据既不落在 SQL 文件里, 也不会留在 shell 历史中:
--
--   export MP_DB_USER="${MP_DB_USER:-meal_planner}"
--   export MP_DB_PASSWORD='<强密码>'          # 生产: 建议从密码管理器读取
--   envsubst '$MP_DB_USER $MP_DB_PASSWORD' < deploy/mysql/01-create-database.sql \
--     | mysql -u root -p
--
-- 没有 envsubst 时用 sed 也可以:
--   sed -e "s/\${MP_DB_USER}/$MP_DB_USER/" -e "s/\${MP_DB_PASSWORD}/$MP_DB_PASSWORD/" \
--     deploy/mysql/01-create-database.sql | mysql -u root -p
--
-- 之后把同一个密码写进 .env 的 APP__DATABASE__URL (模板见 .env.example)。

CREATE DATABASE IF NOT EXISTS meal_planner
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS meal_planner_test
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

-- ${MP_DB_USER} / ${MP_DB_PASSWORD} 是占位符, 执行前必须完成上面的替换,
-- 直接原文执行会创建一个密码为字面量的账号。
CREATE USER IF NOT EXISTS '${MP_DB_USER}'@'127.0.0.1' IDENTIFIED BY '${MP_DB_PASSWORD}';
ALTER USER '${MP_DB_USER}'@'127.0.0.1' IDENTIFIED BY '${MP_DB_PASSWORD}';
CREATE USER IF NOT EXISTS '${MP_DB_USER}'@'localhost' IDENTIFIED BY '${MP_DB_PASSWORD}';
ALTER USER '${MP_DB_USER}'@'localhost' IDENTIFIED BY '${MP_DB_PASSWORD}';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON meal_planner.* TO '${MP_DB_USER}'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON meal_planner_test.* TO '${MP_DB_USER}'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON meal_planner.* TO '${MP_DB_USER}'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON meal_planner_test.* TO '${MP_DB_USER}'@'localhost';

FLUSH PRIVILEGES;
