/**
 * 机器人状态卡 - 飞书连接 + 定时推送 + 最近推送记录
 *
 * 只读真实状态, 不做"界面能开但实际不生效"的开关: 推送开关仍然由服务端
 * APP__SCHEDULER__ENABLED 控制, 这里只是诚实地把它显示出来。
 */
import { Text, View } from '@tarojs/components'

import type { AutomationStatus } from '@shared/types'

import { Card, Chip, LoadingStack, SetGroup, SetRow } from './ui'

interface Props {
  status: AutomationStatus | null
  error: string
}

export function AutomationCard({ status, error }: Props) {
  if (error) {
    return (
      <Card>
        <Text className="card__label">飞书机器人</Text>
        <View className="card__hint">读不到状态: {error}</View>
      </Card>
    )
  }
  if (!status) return <LoadingStack rows={2} />

  const { feishu, scheduler, reminders, notifications } = status
  return (
    <View style={{ marginTop: 14 }}>
      <Card>
        <View className="card__head">
          <Text className="card__label">飞书机器人</Text>
          <Chip tone={feishu.configured && feishu.bound ? 'accent' : 'default'}>
            {feishu.configured ? (feishu.bound ? '已连接' : '未绑定') : '未配置'}
          </Chip>
        </View>
        <View className="card__hint">
          {feishu.configured
            ? feishu.bound
              ? '到点会把菜单推到你的飞书'
              : '应用已配置, 但当前账号不是飞书登录, 收不到推送'
            : '还没有配置飞书应用, 推送暂不可用'}
        </View>
        {notifications.length > 0 ? (
          <View style={{ marginTop: 10 }}>
            {notifications.slice(0, 4).map((item) => (
              <View key={item.id} className="inv-row">
                <View style={{ flex: 1 }}>
                  <Text className="inv-row__name">{item.title}</Text>
                  <View className="inv-row__meta">
                    {item.occurred_at.replace('T', ' ').slice(5, 16)} · {item.status}
                  </View>
                </View>
              </View>
            ))}
          </View>
        ) : null}
      </Card>

      <SetGroup title="定时推送">
        <SetRow
          label="推送开关"
          state={scheduler.enabled ? 'ok' : 'warn'}
          value={scheduler.enabled ? '已开启' : '未开启'}
        />
        <SetRow label="菜单推送" value={`工作日 ${reminders.daily_menu_push}`} />
        <SetRow label="库存检查" value={`工作日 ${reminders.evening_check}`} />
        <SetRow label="最近一次推送" value={feishu.last_push_at ? feishu.last_push_at.replace('T', ' ').slice(5, 16) : '暂无记录'} />
      </SetGroup>

      <View className="sheet__hint">{reminders.note}</View>
    </View>
  )
}

export default AutomationCard
