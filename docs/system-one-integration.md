# System One 决策模型集成说明（默认后端：开源 Laya）

## 它是什么

System One 决策模型是**非自回归**的一类模型：喂一段状态（state）加一组类型化问题，
**单次前向传播**直接输出带校准概率的结构化结果，不做 token 生成，因此也不存在
"返回的 JSON 解析失败"，从架构上消除了生成式幻觉。

只有三种原语：

| 原语 | 用途 | 返回 |
|---|---|---|
| `choice` | 从预定义选项中选唯一项（分类、路由） | choice + 概率分布 + confidence |
| `score` | 按 2-10 个有序等级评估（程度、强度） | score + 概率分布 + confidence |
| `noul` | 判断一个陈述是否为真 | 校准后的 P(true)，0-1 |

一次请求里的**所有问题并行求解**，加问题几乎不增加耗时。

### 为什么默认用 Laya 而不是 Jev

Jev（TypeSafe AI，2026-09-15 发布）是这个范式的闭源代表，但它是商业 API：
按 token 计费（\$0.042/百万）、需要官方白名单开白（**无自助注册入口**，
`console.typesafe.ai` 直接 307 跳 `/login`），且中文媒体提到尚未对中国大陆开放。

**Laya** 是它的开源平替（Apache-2.0，`convaiinnovations/laya`，421M 参数）：
本地推理、零调用成本、可私有化部署，接口与 Jev 对齐（同为 choice/score/noul）。

| 维度 | TypeSafe Jev | Laya |
|---|---|---|
| 权重 | 闭源 API，无本地权重 | Apache-2.0，完整权重 |
| 部署 | 云端调用 | 本地 / 私有化，消费级 GPU 或 CPU 均可 |
| 成本 | \$0.042 / 百万 token | 0 |
| 延迟 | 70–500ms（第三方 p50 236–276ms） | 32.8ms 量级 |
| 校准 | ECE 0.246 | ECE 0.081 |

## 落点：为什么是「口语诉求解析」，而不是打分排序

饭决的决策引擎有三条硬约束：**2 秒内响应**、**规则驱动**、**Python 与
`shared/decide.ts` 离线双端同构**（文案被 fixture 逐字钉死）。

把模型塞进打分排序会同时破坏这三条，而且不划算：忌口过滤、7 天不重复、品类打散、
库存命中这些规则本来又快又可解释，那是"拿 System One 干 System Two 的活"。

规则真正做不了的是用户那句口语——"今天想吃清淡点的，别太辣，冰箱里还有鸡蛋"。
穷举不了，而这恰好是 System One 的强项。所以分工是：

> **模型负责「听懂」，规则负责「决定」。听不懂就当没听见，照常出菜。**

## 四种 provider

| provider | 说明 | 何时用 |
|---|---|---|
| `laya` | **默认**。开源 Laya，本地推理，无需 Key、无网络调用 | 生产默认 |
| `jev` | 官方 TypeSafe API | 已通过白名单且愿意付调用费 |
| `adapter` | 官方开源适配器，背后接 OpenAI 兼容端点（LM Studio） | 机器上装不了 torch 的退路 |
| `rule` | 纯规则关键词兜底，零依赖 | 兜底 / 不想引外部依赖 |

接口完全同构，切换只改 `APP__SYSTEM_ONE__PROVIDER` 一行。

## 安装与首次运行

```bash
pip install laya                 # 会带上 torch + transformers（约 2GB）
# 或 pip install -e ".[system-one]"
```

首次运行会从 HuggingFace 下载 421M 权重（约 678MB）。**国内网络需要镜像**：

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

配置（`.env`）：

```bash
APP__SYSTEM_ONE__ENABLED=true
APP__SYSTEM_ONE__PROVIDER=laya
APP__SYSTEM_ONE__LAYA_CHECKPOINT=multilingual   # 中文必选 multilingual 或 auto
APP__SYSTEM_ONE__MIN_CONFIDENCE=0.55
APP__SYSTEM_ONE__NOUL_ACCEPT=0.75
```

冒烟验证：

```bash
python scripts/system_one_smoke.py "今天想吃清淡点的，别太辣，冰箱里还有鸡蛋，赶时间"
```

实测输出（本机 CPU）：

```
provider  = laya / multilingual
权重加载  = 0.0 s      # safetensors，二次启动命中本地缓存
推理耗时  = 252 ms      # 8 个问题一次前向
来源      = laya        # 不是 rule，说明模型真的生效了
  只要清淡 = True   辣度上限 = 0   优先用冰箱 = True   菜系 = 粤菜
```

## Laya 的三个权重

| checkpoint | 编码器 | 适用 |
|---|---|---|
| `english` | ModernBERT-large | 纯英文 |
| `multilingual` | mmBERT-base，**322M** | 100+ 语言，含中文 —— **本项目默认** |
| `typed-decisions` | ModernBERT-large | 工单 / 安全 / 客服 / 链路四类业务微调 |
| `auto` | Router 自动分发 | 混合语种输入 |

⚠ **`english` 权重遇到中文会静默失效**——不报错，只是判得差。中文必须显式用
`multilingual` 或 `auto`。

## API

```
POST /api/decide/understand    只解析诉求，不做决策（前端回显 + 调阈值用）
POST /api/decide               可选传 utterance，据此收敛候选
```

`understood=false` 时前端**不该回显任何东西**——没听懂就当没听见。

## 接入主链路的方式

`DecisionService.decide()` 的可选参数 `utterance`。给了才解析，不给完全不碰模型。
解析结果对候选只做两件事：

1. **减法**：`MealIntent.allows()` 过滤（清淡 / 辣度上限 / 出餐上限 / 不吃肉 / 品类 / 不要X）
2. **加分**：`MealIntent.bonus()` 小幅加分（菜系 +15，优先用冰箱 +6）

若过滤后候选为空（比如"想喝汤"但池里没汤），**整条诉求作废照常出菜**。
打分权重、三条硬规则、离线双端同构均未改动。

## 踩过的坑

1. **不要用多路 Choice 的置信度当总闸。** 最初用 `intent_type`（六选一）把关整体
   结果，模型给它 0.22，于是一堆判断正确的 noul（清淡 0.96、不辣 0.94）被整体否决
   —— 而这个字段本身根本没参与构建意图。多路 Choice 天然比二值 Noul 置信度低，
   让最弱一环决定全部是错的。**改为按问题逐个把关。**

2. **Noul 的 instructions 必须写成「用户明确说出了……」，不能写成「用户想不想……」。**
   这是实测出来的，不是文风偏好。写成"用户想吃素吗"时，Laya 回答的是"这句话是否
   成立/合理"，而不是"用户说没说"，于是根本没提到的"想吃素"拿到 0.715、"想喝汤"
   拿到 0.682，和真实命中项（0.80–0.96）贴得极近，靠调阈值根本分不开——提到 0.78
   又会把真实的"赶时间"(0.80) 卡掉，换句话就掉。

   改成"用户明确说出了想吃素"后，同一句话的实测对照：

   | 信号 | 原措辞 | 强调"明确说出" | 期望 |
   |---|---|---|---|
   | 赶时间 | 0.7986 | **0.8738** | 真 |
   | 清淡 | 0.9603 | 0.9534 | 真 |
   | 冰箱 | 0.8721 | 0.8541 | 真 |
   | 想吃素 | 0.7148 | **0.6051** | 假 |
   | 想喝汤 | 0.6815 | **0.3308** | 假 |

   真假间距从 0.08 拉开到 0.25 以上。**改措辞比调阈值有效得多**——阈值是治标，
   措辞才是治本。这道措辞已被单测钉死（`test_noul_instructions_must_ask_whether_user_said_it`），
   防止有人手滑改回"想不想"句式。

   注意：**单句观测得出的阈值不可信**，上面的 0.75 后来在 106 条语料上被推翻，
   真值见下一节。

3. **Laya 是同步推理，必须丢到线程里跑**（`asyncio.to_thread`），否则阻塞 FastAPI
   整个事件循环。已用单测断言"推理不在主线程上"。

4. **权重要模块级缓存。** FastAPI 每个请求 new 一个 service，实例级缓存等于没缓存。
   且缓存 key 必须按**实例自己的配置**算——用 `get_settings()` 会让 multilingual
   和 english 两个实例串用缓存。

5. **`USE_TF=0`。** transformers 探测到 TensorFlow 时，其 abseil 运行时在 macOS 上
   可能死锁，表现为卡在 import / load。Laya 官方文档明确记录，本项目已处理。

6. **荤素判定要先抠假阳性词。**「鸡蛋」含「鸡」、「鸡精」含「鸡」，不抠掉的话
   用户说"吃素"却连番茄炒蛋都吃不上。

7. **`0 == False` 陷阱。** 判断"字段未设置"时别写 `if value in (False, -1, None)`，
   Python 里 `0 in (False, ...)` 为真，会把"辣度上限 0"误判成未设置。

8. **生产环境若走 WorkBuddy 沙箱之类会代理 `open()` 的运行时**，transformers 启动
   时扫描自身目录（数千次 open）会被文件代理拖超时。这是执行环境的问题，不是
   Laya 的问题——正常 `uvicorn` 进程不受影响。

## 语料校准（已完成）

单句观测出来的阈值不可信，所以建了一套标注语料 + 拟合脚本：

```
data/utterance_corpus.json          106 条中文说法 × 6 个问题 = 636 个判断点
scripts/system_one_calibrate.py     跑模型 → 网格搜阈值 → 输出策略对比与残余误判
output/system-one-calibration.json  每条语料的原始 noul / 置信度, 供人工复核
```

```bash
.venv/bin/python scripts/system_one_calibrate.py            # 42s(含权重加载 23s)
.venv/bin/python scripts/system_one_calibrate.py --write    # 把拟合值写回 default.yaml
```

标注口径与问题措辞严格对齐：每个 bool 标签回答的是「用户**明确说出了**……」，
没说就是 false，哪怕猜起来很合理。语料里刻意留了 10 条否定陷阱
（"今天不想吃清淡的"、"我不赶时间"、"冰箱空了"）和 4 条荤字陷阱
（番茄炒蛋 / 宫保鸡丁 / 鸡蛋羹 / 牛肉面）。

### 拟合出来的是什么

代价函数非对称：**凭空加一条用户没说的约束罚 2 分，漏掉一条罚 1 分**。
目标函数取**线上融合策略的 F1**（不是纯模型的）。

| 策略 | 精确率 | 召回 | F1 |
|---|---|---|---|
| 纯规则（修否定前） | 88% | 75% | 0.81 |
| 纯规则（修否定后） | 95% | 75% | 0.84 |
| 纯模型（旧阈值 0.75/0.35） | 60% | 72% | **0.65** ← 比纯规则还差 |
| 纯模型（拟合阈值 0.91/0.20） | 81% | 33% | 0.47 |
| **模型 + 规则逐维度融合** | 92% | 87% | **0.89** |

拟合阈值跑了两轮（修规则的否定缺陷前后），最优点都稳定落在 `accept=0.91 / reject=0.20`。

结论有三个，都不太好看但都很重要：

1. **原来的"整体退回规则"写法是错的。** 它只在"所有问题都落在不确定区"时才用
   规则，而真实阈值下这种情况几乎不发生 —— 结果模型路径（F1 0.65）反而拖累了
   纯规则（0.81）。改成**逐维度融合**：模型判 True/False（有把握）就听模型，
   判 None（中间地带）才听规则。这是 `intent_service._from_model()` 现在的行为。

2. **规则那边也抓出了一个真 bug：关键词匹配看不见否定。** "今天不想吃清淡的"里
   明明有"清淡"两个字，意思却是反的。残余误判 21 条里有 5 条是这个（"不想吃清淡"、
   "不用着急"、"冰箱空了"、"别给我汤"、"别给我清淡的"）。修法是**按标点切分后
   抠掉含否定词的分句**，而且只作用于正向偏好（清淡/赶时间/冰箱/喝汤）——排除型
   诉求（不吃辣、不吃肉）本身就是否定形式，再否定一次就反了。纯规则 FP 8→3。

3. **零样本上限就在这。** Laya multilingual 权重在中文上的六个问题**真假间距全为负**
   （真信号最低值 < 假信号最高值，最差的 `use_fridge` 差 0.67）。阈值只能在
   "高精确率低召回"这个角上取最优，调不出既准又全的点。菜系 Choice 更糟：
   命中率随置信度阈值单调上升，到 0.90 也才 67%（触发 6/106）。

### 顺带证伪的两个猜想

- **并行多问会串扰吗？不会。** 同一个指令下单问与九问并行，输出完全一致
  （"不吃辣"的 use_fridge 都是 0.680）。分批提问只影响耗时，不影响质量。
- **分批提问能提质量吗？不能。** batch=1/2/3/9 的拟合结果与真假间距逐位相同。
  耗时倒是真的线性：单问 296 ms/条 → 九问 232 ms/条（九问摊薄后更划算）。

（这两个猜想最初是被一个假象带偏的：改指令里的逗号（`,` vs `，`）就让
use_fridge 从 0.207 跳到 0.680。**指令文本极其敏感，但和并行数量无关。**）

## 上线前必须做

Laya 官方明确指出：**零样本能力弱，生产务必用专项微调权重并完成温度校准**。

已经做完的：语料 106 条、阈值按语料拟合（0.91 / 0.20 / 0.90）、策略改为逐维度融合。

剩下的（想再往上只能动权重，调阈值没用了）：

1. 用自有数据微调权重，然后把 `laya_model` 指向自己的仓库
2. 微调后**重跑一次** `scripts/system_one_calibrate.py --write`
3. 语料要持续补：现在 106 条里真实用户说法为 0，全是构造的，上线后要把
   `/api/decide/understand` 的真实 utterance 沉淀进来再拟合

另外：choice 选项数控制在 20 以内（超了准确率快速衰减）；
score 是三种原语里最弱的，原生权重置信度普遍偏高。

## 文件

| 文件 | 职责 |
|---|---|
| `backend/app/config.py` | `SystemOneSettings`（provider 四档 + 阈值 + Laya 权重） |
| `backend/app/services/system_one_service.py` | 接入层：归一化 + 权重缓存 + 线程卸载 + 降级 |
| `backend/app/services/intent_service.py` | 口语诉求 → `MealIntent`（含规则兜底） |
| `backend/app/api/decide.py` | `POST /decide/understand`；`decide` 增加 utterance |
| `backend/app/services/decision_service.py` | 意图做减法过滤 + 小幅加分 |
| `scripts/system_one_smoke.py` | 一句话冒烟：通不通、听懂了什么 |
| `data/utterance_corpus.json` | 106 条中文语料 + 标注（阈值拟合基准） |
| `scripts/system_one_calibrate.py` | 跑语料 → 拟合阈值 → 策略对比 + 残余误判 |
| `backend/tests/unit/test_system_one_service.py` | 归一化 / 降级 / 缓存 / Laya 接线 |
| `backend/tests/unit/test_intent_service.py` | 规则兜底 / 模型映射 / 逐级把关 |
