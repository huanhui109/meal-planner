import { useEffect, useState } from 'react'
import { Image, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'

import { brand } from '@shared/brand'

import { Card, PageHead, SetGroup, SetRow } from '../../components/ui'
import { BRAND_HOST } from '../../lib/config'
import { openCustomerServiceChat } from '../../lib/customer-service'
import { LOGO_MARK_DATA_URI, LOGO_MARK_DATA_URI_DARK } from '../../lib/logo'
import { useTheme } from '../../lib/theme'

/** 关于页 - 品牌卡 + 版本号 + 隐私/条款/反馈/客服入口 (audit T1.3 P0 + T2.4 检查更新)

  进入路径: profile → 「关于」, 微信后台「小程序信息」也可以链过来
  隐私/条款文档上线后会托管在 docs.example.com; 内测期间 modal 提示
*/
export default function AboutPage() {
  const [, , applied] = useTheme()
  const [version, setVersion] = useState('')
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    try {
      const app = Taro.getApp?.() as { version?: string } | undefined
      if (app?.version) setVersion(app.version)
    } catch {
      /* ignore */
    }
  }, [])

  // 亮色 UI 用深容框, 暗色 UI 用白容框 (与 H5 LogoMark 规则一致)
  const logoSrc = applied !== 'cool' ? LOGO_MARK_DATA_URI_DARK : LOGO_MARK_DATA_URI

  const openDoc = (title: string, kind: 'privacy' | 'terms') => {
    const url =
      kind === 'privacy'
        ? 'https://docs.meal.example.com/legal/privacy.html'
        : 'https://docs.meal.example.com/legal/terms.html'
    Taro.showModal({
      title,
      content: `正式版会托管在:\n${url}\n\n内测期间请向开发者索取 Markdown 全文。`,
      showCancel: false,
      confirmText: '知道了',
    })
  }

  const openFeedbackHint = () => {
    Taro.showToast({ title: '请到「我的 → 意见反馈」提交', icon: 'none', duration: 2000 })
  }

  const openCustomerService = () => {
    void openCustomerServiceChat(() => {
      Taro.showToast({ title: '客服暂未开启, 请到「我的」提交反馈', icon: 'none', duration: 2500 })
    })
  }

  const handleCheckUpdate = async () => {
    setChecking(true)
    try {
      const { checkForUpdateManual } = await import('../../lib/build')
      const result = await checkForUpdateManual()
      if (result.status === 'up_to_date') {
        Taro.showToast({ title: '已是最新版本', icon: 'success' })
      } else if (result.status === 'optional') {
        Taro.showModal({
          title: '新版本可用',
          content: `最新 v${result.latest}, 您当前 v${result.current}\n${result.notes || ''}`,
          confirmText: '查看更新',
          cancelText: '稍后',
        })
      } else if (result.status === 'force') {
        Taro.reLaunch({ url: '/pages/update/index' })
      } else if (result.status === 'error') {
        Taro.showToast({ title: result.message, icon: 'none', duration: 2500 })
      }
    } finally {
      setChecking(false)
    }
  }

  return (
    <View className="page">
      <PageHead title="关于" subtitle="品牌与版本信息" />

      <Card>
        <View style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Image
            src={logoSrc}
            style={{ width: 56, height: 56, borderRadius: 14, flexShrink: 0 }}
            mode="aspectFit"
          />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-ink)' }}>
              {brand.name}
            </Text>
            <View className="card__hint" style={{ marginTop: 4 }}>
              {brand.subtitle}
            </View>
          </View>
        </View>
        <View style={{ marginTop: 16 }}>
          <Text style={{ fontSize: 14, color: 'var(--color-ink)', lineHeight: 1.6 }}>
            {brand.description}
          </Text>
        </View>
        <View className="card__hint" style={{ marginTop: 12 }}>
          {brand.localDataNote}
        </View>
      </Card>

      <View className="page-footnote">
        {version ? `当前版本: v${version}` : '当前版本: 加载中…'}
        {'\n'}
        数据存放: {BRAND_HOST}
      </View>

      <View style={{ marginTop: 16 }}>
        <SetGroup title="合规">
          <SetRow
            label="隐私协议"
            state="ok"
            value="已发布"
            onClick={() => openDoc('隐私协议', 'privacy')}
          />
          <SetRow
            label="服务条款"
            state="ok"
            value="已发布"
            onClick={() => openDoc('服务条款', 'terms')}
          />
        </SetGroup>

        <SetGroup title="支持">
          <SetRow label="意见反馈" value="提交" onClick={openFeedbackHint} />
          <SetRow label="在线客服" value="咨询" onClick={openCustomerService} />
        </SetGroup>

        <SetGroup title="关于">
          <SetRow label="版本" value={version ? `v${version}` : '加载中…'} />
          <SetRow label="数据存放" value={BRAND_HOST} />
          <SetRow
            label="检查更新"
            value={checking ? '检测中…' : '点这里'}
            onClick={handleCheckUpdate}
          />
        </SetGroup>
      </View>

      <View className="page-footnote" style={{ marginTop: 24 }}>
        © {new Date().getFullYear()} 每周鲜 · AI 营养菜谱
        {'\n'}
        本应用为内测灰度版本, 数据可能随时清空, 请勿用于生产决策。
      </View>
    </View>
  )
}
