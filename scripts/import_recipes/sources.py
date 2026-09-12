"""数据源抓取 - 带本地缓存的 HowToCook 与 proj.kitchen 采集

proj.kitchen 文档明确提示"服务器资源有限", 所以原始响应一律先落 ``.cache/recipes``,
只有缓存缺失或 ``force=True`` 时才联网。HowToCook 用浅克隆, 已存在则 ``git pull``。
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

PROJ_KITCHEN_INDEX_URL = "https://proj.kitchen/api/recipes"
PROJ_KITCHEN_DETAIL_URL = "https://proj.kitchen/api/recipes/{id}"
# HowToCook: 用 GitHub API 列文件 + 拉原始 markdown, 比整仓浅克隆稳得多
HOWTOCOOK_TREE_URL = "https://api.github.com/repos/Anduin2017/HowToCook/git/trees/{branch}?recursive=1"
HOWTOCOOK_RAW_URL = "https://raw.githubusercontent.com/Anduin2017/HowToCook/{branch}/{path}"
HOWTOCOOK_BRANCH = "master"

REQUEST_TIMEOUT = 20.0
REQUEST_INTERVAL = 0.15  # 秒; 对 proj.kitchen 手下留情
FETCH_WORKERS = 8  # HowToCook 原始文件并发数


@dataclass
class RawRecipe:
    """一条尚未归一化的原始菜谱"""

    source: str  # proj_kitchen / howtocook
    key: str  # 源内唯一标识 (id 或文件路径)
    payload: object  # dict (proj.kitchen) 或 str (markdown 文本)


def _ensure_dir(path: Path) -> None:
    """幂等建目录

    沙箱/部分文件系统下对已存在目录调 ``mkdir(exist_ok=True)`` 会抛
    ``PermissionError(EEXIST)``, 所以先判断再建, 避免误伤已缓存的数据。
    """
    if path.is_dir():
        return
    path.mkdir(parents=True, exist_ok=True)


def _client() -> httpx.Client:
    return httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True, headers={"User-Agent": "meal-planner-importer/1.0"})


def _get_json(client: httpx.Client, url: str, retries: int = 3) -> Optional[object]:
    for attempt in range(1, retries + 1):
        try:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - 网络抖动要能重试
            logger.warning("请求失败 (%s/%s) %s: %s", attempt, retries, url, exc)
            time.sleep(0.5 * attempt)
    return None


def fetch_proj_kitchen(cache_dir: Path, force: bool = False) -> List[RawRecipe]:
    """抓取 proj.kitchen 全量菜谱 (索引 + 逐条详情), 落缓存"""
    base = cache_dir / "proj_kitchen"
    _ensure_dir(base)
    index_path = base / "index.json"

    if force or not index_path.exists():
        with _client() as client:
            index = _get_json(client, PROJ_KITCHEN_INDEX_URL)
        if not index:
            if index_path.exists():
                logger.warning("proj.kitchen 索引抓取失败, 沿用旧缓存")
                index = json.loads(index_path.read_text(encoding="utf-8"))
            else:
                logger.error("proj.kitchen 索引抓取失败且无缓存, 跳过该源")
                return []
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    index = json.loads(index_path.read_text(encoding="utf-8"))
    detail_dir = base / "recipes"
    _ensure_dir(detail_dir)

    recipes: List[RawRecipe] = []
    fetched = 0
    with _client() as client:
        for entry in index:
            rid = entry.get("id")
            name = entry.get("name")
            if not rid and not name:
                continue
            key = rid or name
            path = detail_dir / f"{_safe_filename(str(key))}.json"
            if force or not path.exists():
                detail = _get_json(client, PROJ_KITCHEN_DETAIL_URL.format(id=quote(str(key), safe="")))
                if detail:
                    path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
                    fetched += 1
                time.sleep(REQUEST_INTERVAL)
            if path.exists():
                recipes.append(RawRecipe("proj_kitchen", str(key), json.loads(path.read_text(encoding="utf-8"))))
            else:
                # 详情缺失时退回索引条目 (至少保住菜名与分类)
                recipes.append(RawRecipe("proj_kitchen", str(key), entry))
    logger.info("proj.kitchen: 索引 %s 条, 本次新抓 %s 条详情, 可用 %s 条", len(index), fetched, len(recipes))
    return recipes


def _list_howtocook_paths(client: httpx.Client) -> List[str]:
    """列出 HowToCook 仓库里全部菜谱 markdown (排除模板与厨房准备类文档)"""
    tree = _get_json(client, HOWTOCOOK_TREE_URL.format(branch=HOWTOCOOK_BRANCH))
    if not isinstance(tree, dict):
        return []
    paths: List[str] = []
    for item in tree.get("tree", []):
        path = item.get("path", "")
        if not path.startswith("dishes/") or not path.endswith(".md"):
            continue
        if path.startswith("dishes/template/"):
            continue
        paths.append(path)
    return sorted(paths)


def _fetch_one_raw(client: httpx.Client, branch: str, path: str, target: Path) -> bool:
    try:
        resp = client.get(HOWTOCOOK_RAW_URL.format(branch=branch, path=quote(path, safe="/")))
        resp.raise_for_status()
        _ensure_dir(target.parent)
        target.write_text(resp.text, encoding="utf-8")
        return True
    except Exception as exc:  # noqa: BLE001 - 单个文件失败不影响整体
        logger.warning("HowToCook 拉取失败 %s: %s", path, exc)
        return False


def fetch_howtocook(cache_dir: Path, force: bool = False) -> List[RawRecipe]:
    """通过 GitHub API 拉取 HowToCook 全部菜谱 markdown 并缓存"""
    base = cache_dir / "howtocook"
    files_dir = base / "files"
    _ensure_dir(base)
    index_path = base / "index.json"

    if force or not index_path.exists():
        with _client() as client:
            paths = _list_howtocook_paths(client)
        if not paths:
            if index_path.exists():
                logger.warning("HowToCook 文件列表抓取失败, 沿用旧缓存")
                paths = json.loads(index_path.read_text(encoding="utf-8"))
            else:
                logger.error("HowToCook 文件列表抓取失败且无缓存, 跳过该源")
                return []
        index_path.write_text(json.dumps(paths, ensure_ascii=False, indent=2), encoding="utf-8")

    paths = json.loads(index_path.read_text(encoding="utf-8"))
    todo = [p for p in paths if force or not (files_dir / p).exists()]
    if todo:
        logger.info("HowToCook: 需拉取 %s 篇 (共 %s)", len(todo), len(paths))
        with _client() as client, ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = [pool.submit(_fetch_one_raw, client, HOWTOCOOK_BRANCH, p, files_dir / p) for p in todo]
            for future in as_completed(futures):
                future.result()

    recipes: List[RawRecipe] = []
    for path in paths:
        local = files_dir / path
        if not local.exists():
            continue
        try:
            text = local.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("读取失败 %s: %s", local, exc)
            continue
        # dishes/<category>/... -> 分类取目录名
        parts = path.split("/")
        category = parts[1] if len(parts) > 2 else ""
        recipes.append(RawRecipe("howtocook", path, {"category": category, "text": text}))
    logger.info("HowToCook: 可用 %s 篇菜谱", len(recipes))
    return recipes


def _safe_filename(name: str) -> str:
    """把中文/特殊字符的 id 变成安全的文件名"""
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)[:120] or "recipe"


ALL_SOURCES = {
    "proj_kitchen": fetch_proj_kitchen,
    "howtocook": fetch_howtocook,
}


def fetch_all(cache_dir: Path, force: bool = False, sources: Optional[Dict[str, bool]] = None) -> List[RawRecipe]:
    """抓取全部启用源"""
    enabled = sources or {"proj_kitchen": True, "howtocook": True}
    out: List[RawRecipe] = []
    for name, fetcher in ALL_SOURCES.items():
        if enabled.get(name):
            try:
                out.extend(fetcher(cache_dir, force=force))
            except Exception as exc:  # noqa: BLE001 - 单源失败不影响另一源
                logger.error("%s 抓取失败: %s", name, exc)
    return out
