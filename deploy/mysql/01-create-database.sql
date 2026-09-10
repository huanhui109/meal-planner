-- 以 root 执行: mysql -u root -p < deploy/mysql/01-create-database.sql
-- 生产与测试分库; 应用账号只授权业务库, 不做 DDL 以外的越权操作。

CREATE DATABASE IF NOT EXISTS meal_planner
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS meal_planner_test
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

-- 请把 change-me 换成强密码, 并同步写入 .env 的 APP__DATABASE__URL
CREATE USER IF NOT EXISTS 'meal_planner'@'127.0.0.1' IDENTIFIED BY 'change-me';

GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON meal_planner.* TO 'meal_planner'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON meal_planner_test.* TO 'meal_planner'@'127.0.0.1';

FLUSH PRIVILEGES;
