/**
 * 邀请好友 (audit T3.1) - 生成专属邀请码 / 复制分享 / 兑换别人的码
 *
 * 奖励: 双方各 +3 次 AI 生成额度 (后端记 activity_log, 真实额度表待接入)
 */
import { useEffect, useState } from 'react'
import Taro, { useRouter } from '@tarojs/taro'
import { Input, Text, View } from '@tarojs/components'

import { Card, Chip, LoadingStack, PageHead, PillButton, StatTile } from '../../components/ui'
import { getInviteCode, redeemInviteCode } from '../../lib/api'
import { track } from '../../lib/events'
import { toast } from '../../lib/nav'

export default function InvitePage() {
  const router = useRouter<{ code?: string }>()
  const [code, setCode] = useState('')
  const [sharePath, setSharePath] = useState('')
  const [inviteCount, setInviteCount] = useState(0)
  const [reward, setReward] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [inputCode, setInputCode] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    void load()
    // 从分享链接带过来的 invite_code 自动填上
    if (router.params.code) {
      setInputCode(router.params.code)
    }
  }, [router.params.code])

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getInviteCode()
      setCode(data.code)
      setSharePath(data.share_path)
      setInviteCount(data.invite_count)
      setReward(data.reward_granted)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = () => {
    if (!code) return
    Taro.setClipboardData({ data: code })
    track('invite_copy', { code })
    toast('邀请码已复制', 'success')
  }

  const handleRedeem = async () => {
    const trimmed = inputCode.trim().toLowerCase()
    if (trimmed.length < 4) {
      toast('请填写 4 位以上的邀请码')
      return
    }
    setSubmitting(true)
    try {
      const result = await redeemInviteCode(trimmed)
      toast(result.message, 'success')
      track('invite_redeem', { code: trimmed })
      setInputCode('')
      void load()
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <View className="page">
      <PageHead title="邀请好友" subtitle="双方各得 3 次 AI 生成额度" />

      {loading ? <LoadingStack rows={3} /> : null}
      {error && !loading ? <Card><View className="card__hint">{error}</View></Card> : null}

      {!loading && !error ? (
        <>
          <Card>
            <Text className="card__label">我的邀请码</Text>
            <View
              style={{
                marginTop: 10,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <Text
                style={{
                  fontSize: 28,
                  fontWeight: 700,
                  letterSpacing: 4,
                  color: 'var(--color-ink)',
                }}
              >
                {code}
              </Text>
              <Chip tone="accent">{inviteCount} 人已加入</Chip>
            </View>
            <View style={{ marginTop: 14 }}>
              <PillButton block onClick={handleCopy}>
                复制邀请码
              </PillButton>
            </View>
          </Card>

          <View style={{ display: 'flex', gap: 12, marginTop: 12 }}>
            <StatTile
              label="已邀请"
              value={String(inviteCount)}
              unit="人"
              hint="成功兑换的好友数"
            />
            <StatTile
              label="到账额度"
              value={String(reward)}
              unit="次"
              tone="accent"
              hint="3 次 / 人"
            />
          </View>

          <Card style={{ marginTop: 12 }}>
            <Text className="card__label">兑换好友的邀请码</Text>
            <View style={{ marginTop: 10 }}>
              <Input
                className="text-input"
                value={inputCode}
                placeholder="填写好友给你的邀请码"
                maxlength={20}
                onInput={(e) => setInputCode(e.detail.value)}
              />
            </View>
            <View style={{ marginTop: 12 }}>
              <PillButton block disabled={submitting} onClick={handleRedeem}>
                {submitting ? '兑换中…' : '兑换'}
              </PillButton>
            </View>
          </Card>

          <View className="page-footnote" style={{ marginTop: 20 }}>
            分享路径: {sharePath || '/pages/today/index?invite_code=xxxx'}
            {'\n'}
            好友从这个路径进来会自动填上邀请码
          </View>
        </>
      ) : null}

      <View style={{ height: 24 }} />
    </View>
  )
}
