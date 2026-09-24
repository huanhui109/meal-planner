/**
 * 强制更新页 - audit T2.4
 * 从 app.ts / lib/build.ts 跳进来, 用户除了升级以外没有别的选择
 */
import { useEffect, useState } from 'react'
import { Button, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { Card, PageHead, PillButton } from '../../components/ui'
import { useThemeClass } from '../../lib/theme'

export default function UpdatePage() {
  const themeClass = useThemeClass()
  const [updateUrl, setUpdateUrl] = useState<string | null>(null)
  const [notes, setNotes] = useState<string | null>(null)
  const [latest, setLatest] = useState<string>('')
  const [current, setCurrent] = useState<string>('')

  useEffect(() => {
    try {
      const cache = Taro.getStorageSync('mp:build-info:v1')
      if (cache) {
        const info = JSON.parse(cache) as {
          latest_version: string
          notes: string | null
          update_url: string | null
        }
        setLatest(info.latest_version)
        setNotes(info.notes)
        setUpdateUrl(info.update_url)
      }
      const app = Taro.getApp?.() as { version?: string } | undefined
      if (app?.version) setCurrent(app.version)
    } catch {
      /* ignore */
    }
  }, [])

  const handleCopy = () => {
    if (!updateUrl) return
    Taro.setClipboardData({ data: updateUrl })
    Taro.showToast({ title: '已复制更新链接', icon: 'success' })
  }

  return (
    <View className={`page ${themeClass}`}>
      <PageHead title="需要更新" subtitle="当前版本过低, 请升级到最新版" />

      <Card>
        <Text className="card__label">当前版本</Text>
        <View className="card__value" style={{ marginTop: 4, marginBottom: 12 }}>
          <Text className="num">v{current || '未知'}</Text>
        </View>
        <Text className="card__label">最新版本</Text>
        <View className="card__value" style={{ marginTop: 4, color: 'var(--color-accent-ink)' }}>
          <Text className="num">v{latest || '加载中…'}</Text>
        </View>
      </Card>

      {notes ? (
        <Card>
          <Text className="card__label">本次更新</Text>
          <View style={{ marginTop: 8, fontSize: 14, lineHeight: 1.7, color: 'var(--color-ink)' }}>
            {notes}
          </View>
        </Card>
      ) : null}

      <View style={{ marginTop: 24, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <PillButton block onClick={handleCopy} disabled={!updateUrl}>
          复制更新链接
        </PillButton>
        <Button
          openType="contact"
          className="pill pill--ghost pill--block tap"
          style={{ border: 0 }}
        >
          联系开发者
        </Button>
      </View>

      <View className="page-footnote" style={{ marginTop: 24 }}>
        内测灰度期间可能频繁更新, 给您带来不便请见谅。WeCom/微信扫码后可在「设置 - 关于」内手动更新。
      </View>
    </View>
  )
}
