"""System One 决策模型接入层

Jev 与 Laya 属于同一类模型: **非自回归的 System One 决策模型**。喂一段状态文本
(state) 加一组类型化问题, 单次前向传播直接输出带校准概率的结构化结果, 只有
choice / score / noul 三种原语, 不生成自由文本 —— 因此也不存在"返回的 JSON 解析
失败", 从架构上消除了生成式幻觉。

    本项目默认用 **Laya**(Apache-2.0 开源, 421M, 本地推理):
    Jev 是闭源商业 API, 按 token 计费且需官方白名单开白。Laya 接口与之对齐,
    本地部署零调用成本、延迟更低、概率校准更好(ECE 0.081 vs 0.246)。

为什么要有这一层:
    laya / typesafe_sdk / system-one-adapter 三家的返回类型各不相同, 而且都可能
    因为权重没下载 / 没开白 / 端点没起 / 超时而拿不到结果。业务代码不该关心这些。
    这一层对外只暴露一种形状: 三个答案 dataclass + ok/degraded。

设计原则与 weather_service 完全一致: **失败静默降级**。
一句口语没读懂最多是"没听懂", 绝不能让"决定吃什么"这件事失败。

provider 四档:
    laya     默认。开源本地模型, 无需 Key, 无网络调用, 可私有化部署。
    jev      官方 TypeSafe API。需要 TYPESAFE_API_KEY 且账号通过白名单开白。
    adapter  官方开源适配器, 背后接 OpenAI 兼容端点(LM Studio 等)。
             适合机器上装不了 torch 但仍想跑模型语义的场景。
    rule     不打任何外部电话, 交给调用方的规则兜底。

用法:
    svc = SystemOneService()
    res = await svc.evaluate(state, {"is_light": NoulQ("用户想吃清淡的")})
    if res.ok:
        p = res.noul("is_light")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from app.config import get_settings

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------------- 问题

@dataclass(frozen=True)
class ChoiceQ:
    """从预定义选项中选出唯一项 (分类 / 路由 / 意图识别)

    options 推荐写成 {选项: 这个选项是什么意思}, 描述写清楚比写长更有用 ——
    模型是在这些描述之间做判别, 描述区分度低时判别就差。
    另外务必留一个兜底选项, 否则模型会被迫在几个都不合适的选项里挑一个。
    Laya 官方还提醒: 选项数控制在 20 以内, 超了准确率会明显衰减。
    """

    instructions: str
    options: Union[Mapping[str, str], Sequence[str]]


@dataclass(frozen=True)
class ScoreQ:
    """按 2-10 个有序等级评估 (程度 / 强度 / 风险)

    levels 必须**同一维度且由低到高**。不是同一维度(如"账单问题/用户生气")
    应该拆成多个问题或改用 Choice。
    注意这是三种原语里最弱的一个, 且原生权重输出的置信度普遍偏高。
    """

    instructions: str
    levels: Sequence[str]


@dataclass(frozen=True)
class NoulQ:
    """判断一个陈述是否为真, 返回 0-1 概率

    注意 0.5 的含义是"模型判不出来", 不是"程度中等"。要程度请用 Score。
    """

    instructions: str


Question = Union[ChoiceQ, ScoreQ, NoulQ]


# -------------------------------------------------------------------------- 答案

@dataclass(frozen=True)
class ChoiceAnswer:
    choice: Optional[str] = None
    confidence: float = 0.0
    probabilities: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreAnswer:
    score: float = 0.0
    confidence: float = 0.0
    probabilities: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class NoulAnswer:
    noul: float = 0.5
    # Jev 的 Noul 没有置信度概念(恒为 0); Laya 会给 max(p, 1-p)。
    # 保留这个字段是为了将来用 Laya 的校准信息做二级把关。
    confidence: float = 0.0


Answer = Union[ChoiceAnswer, ScoreAnswer, NoulAnswer]


@dataclass(frozen=True)
class SystemOneResult:
    """一次 System One 调用的结果

    ok=False 表示这一层没拿到任何可用判断, 调用方应当整体退回规则路径 ——
    注意是"整体退回", 不是"缺的那个问题用默认值补上"。半套模型判断混半套规则
    比纯规则更难排查, 因为说不清结果到底是谁定的。
    """

    provider: str = "none"
    answers: Dict[str, Answer] = field(default_factory=dict)
    ok: bool = False
    degraded: bool = False
    error: str = ""

    def has(self, name: str) -> bool:
        return name in self.answers

    def choice(self, name: str, default: Optional[str] = None) -> Optional[str]:
        ans = self.answers.get(name)
        return ans.choice if isinstance(ans, ChoiceAnswer) else default

    def score(self, name: str, default: float = 0.0) -> float:
        ans = self.answers.get(name)
        return ans.score if isinstance(ans, ScoreAnswer) else default

    def noul(self, name: str, default: float = 0.5) -> float:
        ans = self.answers.get(name)
        return ans.noul if isinstance(ans, NoulAnswer) else default

    def confidence(self, name: str) -> float:
        """Choice / Score 的置信度; 以及 Laya 给 Noul 的 max(p, 1-p)"""
        ans = self.answers.get(name)
        if isinstance(ans, (ChoiceAnswer, ScoreAnswer, NoulAnswer)):
            return ans.confidence
        return 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "ok": self.ok,
            "degraded": self.degraded,
            "error": self.error,
            "answers": {
                name: (
                    {"type": "choice", "choice": a.choice, "confidence": a.confidence,
                     "probabilities": a.probabilities}
                    if isinstance(a, ChoiceAnswer)
                    else {"type": "score", "score": a.score, "confidence": a.confidence}
                    if isinstance(a, ScoreAnswer)
                    else {"type": "noul", "noul": a.noul, "confidence": a.confidence}
                )
                for name, a in self.answers.items()
            },
        }


EMPTY = SystemOneResult()


# ---------------------------------------------------------------- Laya 权重缓存

# 加载一次 421M 权重要几十秒, 绝不能每次请求都 load。这里做**模块级**缓存而不是
# 实例级, 因为 FastAPI 每个请求都会 new 一个 service, 实例级缓存等于没缓存。
_LAYA_CACHE: Dict[tuple, Any] = {}
_LAYA_ROUTER: Any = None


def _laya_agent(model: str, checkpoint: str, device: Optional[str]):
    """按 (model, checkpoint, device) 缓存已加载的 Agent"""
    key = (model, checkpoint, device or "")
    cached = _LAYA_CACHE.get(key)
    if cached is not None:
        return cached
    # transformers 探测到 TensorFlow 时, 其 abseil 运行时在 macOS 上可能死锁,
    # 表现为卡在 import / load。这是 Laya 官方文档明确记录的坑。
    os.environ.setdefault("USE_TF", "0")
    import laya

    t0 = time.perf_counter()
    if checkpoint and checkpoint != "english":
        agent = laya.load(model, device=device or None, subfolder=checkpoint)
    else:
        agent = laya.load(model, device=device or None)
    logger.info("Laya 权重加载完成 (%s/%s): %.1fs", model, checkpoint, time.perf_counter() - t0)
    _LAYA_CACHE[key] = agent
    return agent


def _laya_router(model: str, device: Optional[str], max_loaded: int):
    """checkpoint=auto 时用 Router 自动按语种分发"""
    global _LAYA_ROUTER
    if _LAYA_ROUTER is not None:
        return _LAYA_ROUTER
    os.environ.setdefault("USE_TF", "0")
    import laya

    _LAYA_ROUTER = laya.Router(device=device or None, max_loaded=max_loaded)
    return _LAYA_ROUTER


# -------------------------------------------------------------------------- 服务

class SystemOneService:
    """System One 调用门面

    进程内缓存而不是 Redis: 与天气同理, 一句话口语的解析结果重复利用价值高
    (同一个用户连点两次「换一个」不该打两次模型), 但为它引入 Redis 不划算。
    """

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings().system_one
        self._cache: Dict[str, tuple] = {}
        # 最近一次失败原因。静默降级不等于要黑盒 —— 否则线上"模型一直没生效"
        # 没人知道。日志之外再留一个可编程读取的口子。
        self.last_error: str = ""

    # ---------------------------------------------------------------- 对外

    @property
    def usable(self) -> bool:
        return bool(self.settings.usable)

    async def evaluate(
        self,
        state: Union[str, Mapping[str, Any]],
        questions: Mapping[str, Question],
    ) -> SystemOneResult:
        """对同一份 state 并行求解一组问题

        System One 的关键特性是**多个问题一次调用并行求解**, 加问题几乎不增加
        耗时。所以调用方应该把能想到的独立判断一次问完, 而不是循环调用。
        """
        s = self.settings
        if not s.enabled:
            return EMPTY
        # rule 档不打外部电话: 返回 ok=False, 由调用方走自己的规则
        if s.provider == "rule" or not s.usable:
            return EMPTY

        key = self._cache_key(state, questions)
        hit = self._cache.get(key)
        if hit is not None:
            expires_at, cached = hit
            if expires_at > time.monotonic():
                return cached
            self._cache.pop(key, None)

        result = await self._dispatch(state, questions)
        if s.cache_seconds > 0:
            self._cache[key] = (time.monotonic() + s.cache_seconds, result)
        self.last_error = result.error
        return result

    # ---------------------------------------------------------------- 内部

    async def _dispatch(
        self,
        state: Union[str, Mapping[str, Any]],
        questions: Mapping[str, Question],
    ) -> SystemOneResult:
        s = self.settings
        try:
            if s.provider == "laya":
                return await self._call_laya(state, questions)
            if s.provider == "jev":
                return await self._call_jev(state, questions)
            if s.provider == "adapter":
                return await self._call_adapter(state, questions)
            logger.warning("未知的 System One provider: %s", s.provider)
            return EMPTY
        except Exception as exc:  # noqa: BLE001 —— 任何失败都必须静默降级
            logger.warning("System One 调用失败, 静默降级 (provider=%s): %s", s.provider, exc)
            return SystemOneResult(
                provider=s.provider,
                answers={},
                ok=False,
                degraded=True,
                error=str(exc),
            )

    async def _call_laya(
        self,
        state: Union[str, Mapping[str, Any]],
        questions: Mapping[str, Question],
    ) -> SystemOneResult:
        """开源本地模型。**同步**推理, 必须丢到线程里跑, 否则阻塞事件循环。"""
        s = self.settings

        def _run() -> SystemOneResult:
            raw = _laya_raw_questions(questions)
            if s.laya_checkpoint == "auto":
                router = _laya_router(s.laya_model, s.laya_device or None, s.laya_max_loaded)
                payload = router.predict(state, raw)
            else:
                agent = _laya_agent(s.laya_model, s.laya_checkpoint, s.laya_device or None)
                payload = agent.predict(state, raw)
            return _normalize(payload.get("answers") or {}, "laya")

        return await asyncio.to_thread(_run)

    async def _call_jev(
        self,
        state: Union[str, Mapping[str, Any]],
        questions: Mapping[str, Question],
    ) -> SystemOneResult:
        """官方 TypeSafe API。需要 Key 且账号已开白。"""
        from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

        s = self.settings
        kwargs: Dict[str, Any] = {"timeout": s.timeout_seconds}
        if s.api_key:
            kwargs["api_key"] = s.api_key
        if s.base_url:
            kwargs["base_url"] = s.base_url

        async with AsyncTypeSafeClient(**kwargs) as client:
            response = await client.system_one(
                state=state,
                questions=_build_questions(questions, Choice, Score, Noul),
                model=s.model,
                timeout=s.timeout_seconds,
            )
        return _normalize(getattr(response, "answers", {}) or {}, "jev")

    async def _call_adapter(
        self,
        state: Union[str, Mapping[str, Any]],
        questions: Mapping[str, Question],
    ) -> SystemOneResult:
        """官方开源适配器: 接口同构, 背后接 OpenAI 兼容端点(可以是本机 LM Studio)"""
        from system_one_adapter import AsyncSystemOneAdapterClient, Choice, Noul, Score
        from system_one_adapter.providers.openai import AsyncOpenAIProvider

        s = self.settings
        # 本地端点一般不校验 key, 但 openai 客户端要求非空, 留空会直接抛
        # Missing credentials。另外本地端点通常只实现 Chat Completions,
        # 显式指定以免走 Responses API 404。
        provider = AsyncOpenAIProvider(
            s.adapter_model,
            base_url=s.adapter_base_url,
            api_key=s.adapter_api_key or "local",
            api="chat_completions",
        )
        async with AsyncSystemOneAdapterClient(
            structured_outputs=s.adapter_structured_outputs,
            llm_answer_mode="probabilities",
            normalize_probabilities=True,
        ) as client:
            response = await client.system_one(
                state=state,
                questions=_build_questions(questions, Choice, Score, Noul),
                model=provider,
            )
        return _normalize(getattr(response, "answers", {}) or {}, "adapter")

    def _cache_key(self, state: Union[str, Mapping[str, Any]], questions: Mapping[str, Question]) -> str:
        """缓存 key 必须按**本实例**的配置算, 不能用全局配置

        用 get_settings() 的话, 一个显式指定 laya_checkpoint=english 的实例会命中
        multilingual 实例留下的缓存 —— 两个权重的判断不一样, 串了就是错的。
        """
        s = self.settings
        payload = {
            "state": state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, sort_keys=True),
            "questions": {name: _question_signature(q) for name, q in sorted(questions.items())},
            "model": _model_tag(s),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return f"{hash(raw):x}"


# -------------------------------------------------------------------------- 工具

def _model_tag(s) -> str:
    if s.provider == "laya":
        return f"laya:{s.laya_model}/{s.laya_checkpoint}"
    if s.provider == "jev":
        return f"jev:{s.model}"
    if s.provider == "adapter":
        return f"adapter:{s.adapter_model}"
    return s.provider


def _question_signature(q: Question) -> Dict[str, Any]:
    if isinstance(q, ChoiceQ):
        options = q.options
        if isinstance(options, Mapping):
            options = {str(k): str(v) for k, v in options.items()}
        else:
            options = [str(x) for x in options]
        return {"type": "choice", "instructions": q.instructions, "options": options}
    if isinstance(q, ScoreQ):
        return {"type": "score", "instructions": q.instructions, "levels": [str(x) for x in q.levels]}
    return {"type": "noul", "instructions": q.instructions}


def _laya_raw_questions(questions: Mapping[str, Question]) -> Dict[str, Dict[str, Any]]:
    """Laya 直接用原生 dict 定义问题, 不需要 SDK 的问题类"""
    out: Dict[str, Dict[str, Any]] = {}
    for name, q in questions.items():
        if isinstance(q, ChoiceQ):
            out[name] = {"type": "choice", "instructions": q.instructions, "criteria": dict(q.options)}
        elif isinstance(q, ScoreQ):
            out[name] = {"type": "score", "instructions": q.instructions, "criteria": list(q.levels)}
        elif isinstance(q, NoulQ):
            out[name] = {"type": "noul", "instructions": q.instructions}
        else:
            raise TypeError(f"未知的问题类型: {type(q)!r} (name={name})")
    return out


def _build_questions(
    questions: Mapping[str, Question],
    choice_cls,
    score_cls,
    noul_cls,
) -> Dict[str, Any]:
    """把我们的轻量规格翻译成某个 SDK 的问题对象

    typesafe_sdk 与 system-one-adapter 的 Choice/Score/Noul 字段名一致,
    所以可以共用这段翻译。
    """
    built: Dict[str, Any] = {}
    for name, q in questions.items():
        if isinstance(q, ChoiceQ):
            built[name] = choice_cls(instructions=q.instructions, criteria=q.options)
        elif isinstance(q, ScoreQ):
            built[name] = score_cls(instructions=q.instructions, criteria=list(q.levels))
        elif isinstance(q, NoulQ):
            built[name] = noul_cls(instructions=q.instructions)
        else:
            raise TypeError(f"未知的问题类型: {type(q)!r} (name={name})")
    return built


def _get(answer: Any, key: str, default: Any = None) -> Any:
    """答案可能是 dict(Laya) 也可能是 pydantic 对象(两个 SDK), 统一取值"""
    if isinstance(answer, Mapping):
        return answer.get(key, default)
    return getattr(answer, key, default)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize(answers: Mapping[str, Any], provider: str) -> SystemOneResult:
    """把任一后端的应答统一成我们自己的 dataclass"""
    out: Dict[str, Answer] = {}
    for name, ans in answers.items():
        kind = _get(ans, "type")
        probs = _get(ans, "probabilities") or {}
        probs = {str(k): _as_float(v) for k, v in dict(probs).items()}
        if kind == "choice":
            out[name] = ChoiceAnswer(
                choice=_get(ans, "choice"),
                confidence=_as_float(_get(ans, "confidence", 0.0)),
                probabilities=probs,
            )
        elif kind == "score":
            out[name] = ScoreAnswer(
                score=_as_float(_get(ans, "score", 0.0)),
                confidence=_as_float(_get(ans, "confidence", 0.0)),
                probabilities=probs,
            )
        elif kind == "noul":
            out[name] = NoulAnswer(
                noul=_as_float(_get(ans, "noul", 0.5), 0.5),
                confidence=_as_float(_get(ans, "confidence", 0.0)),
            )
        else:
            logger.warning("System One 返回了未知答案类型, 已跳过: %s -> %r", name, kind)
    return SystemOneResult(provider=provider, answers=out, ok=bool(out))
