"""pytest 全局 fixtures

数据库策略: 集成测试统一跑 MySQL (与生产同方言), 避免"SQLite 上能过"的假绿。
运行前设置:
  export TEST_DATABASE_URL="mysql+aiomysql://user:pwd@127.0.0.1:3306/meal_planner_test?charset=utf8mb4"
未设置时跳过需要数据库的用例。
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
import pytest_asyncio


def _test_database_url() -> str:
    return os.getenv("TEST_DATABASE_URL", "").strip()


def _database_name(url: str) -> str:
    return (urlparse(url).path or "/").lstrip("/")


TEST_DATABASE_URL = _test_database_url()

# 必须在导入 app.* 之前设置, 保证应用引擎指向测试库
if TEST_DATABASE_URL:
    if not _database_name(TEST_DATABASE_URL).endswith("_test"):
        raise RuntimeError("TEST_DATABASE_URL 的库名必须以 _test 结尾, 防止误清生产库")
    os.environ["APP__DATABASE__URL"] = TEST_DATABASE_URL
os.environ.setdefault("APP__AUTH__JWT_SECRET", "test-secret-please-change-0123456789abcdef")
os.environ.setdefault("APP__AUTH__COOKIE_SECURE", "false")


requires_mysql = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="未设置 TEST_DATABASE_URL, 跳过 MySQL 集成测试",
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """会话级引擎: 建表一次, 结束时清空"""
    if not TEST_DATABASE_URL:
        pytest.skip("未设置 TEST_DATABASE_URL, 跳过 MySQL 集成测试")

    from sqlalchemy.ext.asyncio import create_async_engine

    from app.models.base import Base

    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(request):
    """每个集成用例前清空数据 (按外键反序删除)"""
    if "db_engine" not in request.fixturenames or not TEST_DATABASE_URL:
        yield
        return
    engine = request.getfixturevalue("db_engine")
    from sqlalchemy import text

    from app.models.base import Base

    async with engine.begin() as conn:
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        await conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    yield


@pytest_asyncio.fixture
async def db_session(db_engine):
    """直连测试库的会话 (用于准备数据/断言)"""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture(scope="session", autouse=True)
def _register_all_models():
    """确保 Base.metadata 包含全部 17 张表 (create_all 依赖导入顺序)"""
    import app.models  # noqa: F401


@pytest_asyncio.fixture
async def api_client(db_engine):
    """ASGI 客户端: 不触发 lifespan, 因此不会启动后台生成 worker"""
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=False
    ) as client:
        yield client


@pytest.fixture
def auth_headers():
    """构造 Bearer 头, 绕过 Cookie 的 Secure 限制"""
    from app.auth.tokens import create_access_token

    def _make(user_id: int) -> dict:
        return {"Authorization": f"Bearer {create_access_token(user_id)}"}

    return _make
