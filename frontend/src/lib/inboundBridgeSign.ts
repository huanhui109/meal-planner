/**
 * 双向唤醒信封签名 —— 浏览器原生 WebCrypto，零新增 npm 包。
 *
 * 签名算法唯一权威实现是后端 `backend/app/services/inbound_bridge/tokens.py`:
 *   TokenService.canonical  (第 74-105 行, 构造签名串)
 *   TokenService.derive_key (第 69-72 行, 第一步 HMAC)
 *   TokenService.sign       (第 122-136 行, 第二步 HMAC)
 *
 * 逐字对齐要点:
 *  - canonical 的 13 行顺序固定, 与 envelope 字段书写顺序无关;
 *  - 第 13 行是 sha256(stableStringify(data)).hexdigest(), 用 crypto.subtle.digest;
 *  - sig 是两步 HMAC-SHA256, 域分离常量 b"fandecide.inbound.sign.v1" 只用于第一步;
 *  - sig 为 64 位小写 hex; envelope 禁止出现 user_id 等任何多余字段。
 *
 * 令牌明文只作为内存里的字符串参数传入, 绝不写 URL / 日志 / localStorage /
 * sessionStorage / 命令行 / 任务文本 / 出站消息正文。
 */
import {
  INBOUND_ALLOWLIST_VERSION,
  INBOUND_PROTOCOL_VERSION,
} from '@shared/inboundBridge'

/** 签名域分离常量, 与后端 b"fandecide.inbound.sign.v1" 逐字一致 */
const SIGN_DOMAIN = 'fandecide.inbound.sign.v1'

/**
 * 完整入站信封（14 字段 + 可选 sig）。
 * 后端 InboundEnvelope 是 extra="forbid": 任何多余字段（尤其 user_id）一律拒收,
 * 因此这里绝不定义、绝不附带 user_id。
 */
export interface InboundEnvelope {
  v: number
  pair_id: string
  direction: string
  event_type: string
  event_id: string
  task_id: string
  phase: string
  assistant_instance_id: string
  session_id: string
  issued_at: number
  nonce: string
  allowlist_version: string
  data: Record<string, unknown>
  /** 出站时省略; buildSignedEnvelope 计算后补上 */
  sig?: string
}

/** newEnvelope 的入参: 由调用方提供的绑定字段, 其余字段自动生成 */
export interface EnvelopeInput {
  pair_id: string
  direction: string
  event_type: string
  /** 触发类事件用空字符串 ""; 回执类填任务 id */
  task_id: string
  phase: string
  assistant_instance_id: string
  session_id: string
}

/**
 * stableStringify —— 递归排序键的紧凑 JSON 序列化, 等价于 Python:
 *   json.dumps(data, sort_keys=True, separators=(",", ":"),
 *              ensure_ascii=False, allow_nan=False)
 *
 * 对齐说明:
 *  - 对象键递归按字典序排序（我们的 data 键均为 ASCII 标识符, 与 Python sort_keys 一致）;
 *  - 无空白: 用 "," / ":" 拼接, 不插入任何空格;
 *  - 中文不转义: 字符串交给 JSON.stringify, 与 ensure_ascii=False 一致;
 *  - 数字/布尔/null 用标准 JSON 表示; NaN/Infinity 显式抛错, 对齐 allow_nan=False;
 *  - 控制字符转义: Python json.dumps 与 JS JSON.stringify 在 \b \t \n \f \r 及
 *    \u00xx（小写 hex）上一致, 且两者都不转义 "/" 与非 ASCII 字符。
 */
export function stableStringify(value: unknown): string {
  return stringify(value)
}

function stringify(value: unknown): string {
  if (value === null) return 'null'
  const kind = typeof value
  if (kind === 'boolean') return value ? 'true' : 'false'
  if (kind === 'number') {
    const num = value as number
    // allow_nan=False: Python json.dumps 遇到 NaN/Inf 直接拒绝, 这里同样拒绝,
    // 而不是让 JSON.stringify 静默把它们变成 null。
    if (!Number.isFinite(num)) {
      throw new Error('签名数据含 NaN/Infinity，已被拒绝（对齐 allow_nan=False）')
    }
    return JSON.stringify(num)
  }
  if (kind === 'string') return JSON.stringify(value)
  if (Array.isArray(value)) {
    return '[' + value.map(stringify).join(',') + ']'
  }
  if (kind === 'object') {
    const obj = value as Record<string, unknown>
    const keys = Object.keys(obj).sort()
    return '{' + keys.map((key) => JSON.stringify(key) + ':' + stringify(obj[key])).join(',') + '}'
  }
  // undefined / bigint / function / symbol Python json.dumps 无法处理, 一律拒绝。
  throw new Error('签名数据含无法序列化的类型，已被拒绝')
}

/** ArrayBuffer -> 64/32 位小写 hex */
function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * 用 crypto.subtle.digest 计算 data 的稳定哈希（64 位小写 hex）。
 * 这就是后端 canonical 第 13 行的 sha256(...).hexdigest()。
 */
export async function stableDataHash(data: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(stableStringify(data))
  return toHex(await crypto.subtle.digest('SHA-256', bytes))
}

/**
 * canonical 签名串 —— 逐字对齐 TokenService.canonical (tokens.py:91-105)。
 *
 * 注意: WebCrypto 的 digest 是异步的, 而后端 canonical 本身是同步纯拼串函数,
 * 因此这里把「异步算好的 data 哈希」作为参数传入, canonical 保持同步纯函数,
 * 便于跨语言测试向量逐行核对。signEnvelope 负责先算哈希再调用本函数。
 */
export function canonical(envelope: InboundEnvelope, dataHashHex: string): string {
  return [
    String(envelope.v ?? INBOUND_PROTOCOL_VERSION), // str(v)
    envelope.pair_id ?? '',
    envelope.direction ?? '',
    envelope.event_type ?? '',
    envelope.task_id || '', // get("task_id", "") or ""
    envelope.phase ?? '',
    envelope.assistant_instance_id ?? '',
    envelope.session_id ?? '',
    envelope.event_id ?? '',
    String(envelope.issued_at ?? 0), // str(issued_at)
    envelope.nonce ?? '',
    envelope.allowlist_version ?? '',
    dataHashHex, // sha256(stableJSON(data)).hexdigest()
  ].join('\n')
}

async function hmacSha256(keyBytes: BufferSource, message: BufferSource): Promise<ArrayBuffer> {
  const key = await crypto.subtle.importKey(
    'raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  )
  return crypto.subtle.sign('HMAC', key, message)
}

/**
 * 两步 HMAC-SHA256 签名（对齐 tokens.py:135-136）:
 *   signing_key = HMAC(明文令牌 UTF-8, b"fandecide.inbound.sign.v1")   // 32 bytes
 *   sig         = HMAC(signing_key, canonical UTF-8).hexdigest()        // 64 hex
 */
export async function signEnvelope(
  envelope: InboundEnvelope,
  plaintextToken: string,
): Promise<string> {
  if (!plaintextToken || plaintextToken.length > 100) {
    throw new Error('网页侧令牌格式不正确，请重新输入')
  }
  const encoder = new TextEncoder()
  // 第 13 行的数据哈希用 crypto.subtle.digest, 与后端 sha256(stableJSON(data)) 一致。
  const dataHashHex = await stableDataHash(envelope.data)
  const canonicalString = canonical(envelope, dataHashHex)

  // 第一步: 用令牌明文作 raw key, 签域分离常量, 得到 32 字节 signing_key。
  const signingKey = await hmacSha256(
    encoder.encode(plaintextToken),
    encoder.encode(SIGN_DOMAIN),
  )
  // 第二步: 用 signing_key 作 raw key, 签 canonical 串, 转小写 hex。
  const signature = await hmacSha256(signingKey, encoder.encode(canonicalString))
  return toHex(signature)
}

/** 生成一个未签名的信封, 自动填充 v / event_id / nonce / issued_at / allowlist_version */
export function newEnvelope(partial: EnvelopeInput): InboundEnvelope {
  return {
    v: INBOUND_PROTOCOL_VERSION,
    pair_id: partial.pair_id,
    direction: partial.direction,
    event_type: partial.event_type,
    event_id: crypto.randomUUID(),
    task_id: partial.task_id,
    phase: partial.phase,
    assistant_instance_id: partial.assistant_instance_id,
    session_id: partial.session_id,
    issued_at: Math.floor(Date.now() / 1000),
    nonce: crypto.randomUUID(),
    allowlist_version: INBOUND_ALLOWLIST_VERSION,
    data: {},
  }
}

/** 构造 + 签名完整信封（含 sig）, 可直接作为请求体发送 */
export async function buildSignedEnvelope(
  partial: EnvelopeInput,
  data: Record<string, unknown>,
  plaintextToken: string,
): Promise<InboundEnvelope> {
  const envelope = newEnvelope(partial)
  envelope.data = data
  envelope.sig = await signEnvelope(envelope, plaintextToken)
  return envelope
}
