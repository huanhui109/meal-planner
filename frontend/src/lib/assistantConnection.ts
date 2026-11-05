import type { AssistantGrant } from '@shared/meal'

export function grantState(grant: AssistantGrant, now = Date.now()): 'revoked' | 'expired' | 'active' {
  if (grant.revoked_at) return 'revoked'
  // Timezone-less API timestamps use the meal domain's Asia/Shanghai time.
  const expires = /(?:Z|[+-]\d\d:\d\d)$/i.test(grant.expires_at)
    ? grant.expires_at : `${grant.expires_at}+08:00`
  return Date.parse(expires) > now ? 'active' : 'expired'
}

export function authorizationTarget(url: string): string {
  const target = new URL(url)
  if (target.origin !== 'https://www.workbuddy.cn' || target.pathname !== '/openapi/v2/authorize'
    || target.username || target.password) throw new Error('助手授权地址无效')
  return target.href
}
