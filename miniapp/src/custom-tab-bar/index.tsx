/**
 * 自定义 TabBar: 悬浮毛玻璃胶囊 (参考稿样式)
 *
 * 为什么不用原生 tabBar: 原生 tabBar 只能贴底、纯色背景、不能做圆角悬浮与毛玻璃,
 * 参考稿的观感做不出来。图标用 View 画的极简几何形, 不引图片资源, 包体积为 0,
 * 也能跟着主题色一起变。
 */
import { Component } from 'react'
import Taro from '@tarojs/taro'
import { Text, View } from '@tarojs/components'

import { cx } from '../components/ui'

interface TabItem {
  pagePath: string
  text: string
  icon: 'home' | 'calendar' | 'basket' | 'box'
}

const TABS: TabItem[] = [
  { pagePath: '/pages/today/index', text: '今日', icon: 'home' },
  { pagePath: '/pages/menu/index', text: '周菜单', icon: 'calendar' },
  { pagePath: '/pages/shopping/index', text: '采购', icon: 'basket' },
  { pagePath: '/pages/fridge/index', text: '冰箱', icon: 'box' },
]

const ACTIVE = '#1c1c1e'
const IDLE = '#c7c7cc'

/** 极简几何图标: 只用 View 的圆角/边框搭出来, 不依赖字体或图片 */
function TabIcon({ name, color }: { name: TabItem['icon']; color: string }) {
  const base = { borderColor: color }
  switch (name) {
    case 'home':
      return (
        <View className="tabbar__icon" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
          <View
            style={{
              width: 16,
              height: 12,
              borderWidth: 2,
              borderStyle: 'solid',
              borderTopWidth: 0,
              borderBottomLeftRadius: 4,
              borderBottomRightRadius: 4,
              ...base,
            }}
          />
          <View
            style={{
              position: 'absolute',
              width: 12,
              height: 12,
              borderLeftWidth: 2,
              borderTopWidth: 2,
              borderStyle: 'solid',
              transform: 'rotate(45deg)',
              marginBottom: 12,
              ...base,
            }}
          />
        </View>
      )
    case 'calendar':
      return (
        <View className="tabbar__icon" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 3 }}>
          {[0, 1, 2].map((row) => (
            <View key={row} style={{ display: 'flex', gap: 3 }}>
              {[0, 1].map((col) => (
                <View
                  key={col}
                  style={{ width: 7, height: 4, borderRadius: 2, background: color }}
                />
              ))}
            </View>
          ))}
        </View>
      )
    case 'basket':
      return (
        <View className="tabbar__icon" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <View
            style={{
              width: 18,
              height: 13,
              borderWidth: 2,
              borderStyle: 'solid',
              borderTopWidth: 0,
              borderBottomLeftRadius: 7,
              borderBottomRightRadius: 7,
              ...base,
            }}
          />
          <View
            style={{
              width: 10,
              height: 8,
              borderWidth: 2,
              borderStyle: 'solid',
              borderBottomWidth: 0,
              borderTopLeftRadius: 6,
              borderTopRightRadius: 6,
              position: 'absolute',
              top: 0,
              ...base,
            }}
          />
        </View>
      )
    case 'box':
      return (
        <View className="tabbar__icon" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <View style={{ width: 18, height: 12, borderWidth: 2, borderStyle: 'solid', borderRadius: 4, ...base }} />
          <View style={{ width: 10, height: 2, borderRadius: 1, background: color, marginTop: 4 }} />
        </View>
      )
    default:
      return (
        <View className="tabbar__icon" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <View style={{ width: 17, height: 17, borderWidth: 2, borderStyle: 'solid', borderRadius: 9, ...base }} />
          <View
            style={{
              width: 5,
              height: 5,
              borderRadius: 3,
              background: color,
              position: 'absolute',
            }}
          />
        </View>
      )
  }
}

export default class CustomTabBar extends Component<Record<string, never>, { selected: number }> {
  state = { selected: 0 }

  setSelected = (selected: number) => {
    this.setState({ selected })
  }

  handleSwitch = (index: number) => {
    const tab = TABS[index]
    if (!tab) return
    this.setSelected(index)
    Taro.switchTab({ url: tab.pagePath })
  }

  render() {
    const { selected } = this.state
    return (
      <View className="tabbar">
        {TABS.map((tab, index) => {
          const on = index === selected
          return (
            <View
              key={tab.pagePath}
              className="tabbar__item tap"
              onClick={() => this.handleSwitch(index)}
            >
              <TabIcon name={tab.icon} color={on ? ACTIVE : IDLE} />
              <Text className={cx('tabbar__label', on && 'tabbar__label--on')}>{tab.text}</Text>
            </View>
          )
        })}
      </View>
    )
  }
}
