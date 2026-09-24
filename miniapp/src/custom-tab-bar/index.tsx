/**
 * 自定义 TabBar: 悬浮毛玻璃胶囊 (参考稿样式)
 *
 * 为什么不用原生 tabBar: 原生 tabBar 只能贴底、纯色背景、不能做圆角悬浮与毛玻璃,
 * 参考稿的观感做不出来。图标用 View 画的极简几何形, 不引图片资源, 包体积为 0,
 * 也能跟着主题色一起变 (颜色直接读 var(--color-ink) / var(--color-ink3))。
 *
 * ⚠ 自定义 tabBar **不在页面根节点里面**, 拿不到页面 .theme-root 上的 CSS 变量,
 *   var(--color-ink) 会一路回落到 page 的默认调色板 (cream) —— 切主题时 tabBar 不变色。
 *   所以这里自己挂一份 `theme-vars theme-<applied>` (纯变量宿主, 无布局副作用),
 *   并在主题变化时 forceUpdate 重新求值。
 */
import { Component } from 'react'
import Taro from '@tarojs/taro'
import { Text, View } from '@tarojs/components'

import { cx } from '../components/ui'
import { px } from '../lib/px'
import { getApplied, subscribeTheme } from '../lib/theme'

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

// 颜色走 CSS 变量, 真正的色值由 _tokens.scss 的 .theme-vars{} / .theme-vars.theme-*{} 提供。
// tabBar 自己挂 theme-vars 宿主 (见文件头注释), 所以这里能拿到当前主题的色值。
// 选中态用 accent 绿做「少量色彩」点缀, 其余保持中性灰 (苹果式克制配色)。
const ACTIVE = 'var(--color-accent)'
const IDLE = 'var(--color-ink3)'

/** 极简几何图标: 只用 View 的圆角/边框搭出来, 不依赖字体或图片 */
function TabIcon({ name, color }: { name: TabItem['icon']; color: string }) {
  const base = { borderColor: color }
  switch (name) {
    case 'home':
      return (
        <View className="tabbar__icon" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
          <View
            style={{
              width: px(16),
              height: px(12),
              borderWidth: px(2),
              borderStyle: 'solid',
              borderTopWidth: 0,
              borderBottomLeftRadius: px(4),
              borderBottomRightRadius: px(4),
              ...base,
            }}
          />
          <View
            style={{
              position: 'absolute',
              /* 必须自己给锚点: .tabbar__icon 是 22x22 的盒子 (position:relative),
                 不给 top/left 时绝对定位会退到 .tabbar (position:fixed) 而飞走 */
              top: 0,
              left: '50%',
              transform: 'translateX(-50%) rotate(45deg)',
              width: px(12),
              height: px(12),
              borderLeftWidth: px(2),
              borderTopWidth: px(2),
              borderStyle: 'solid',
              ...base,
            }}
          />
        </View>
      )
    case 'calendar':
      return (
        <View className="tabbar__icon" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: px(3) }}>
          {[0, 1, 2].map((row) => (
            <View key={row} style={{ display: 'flex', gap: px(3) }}>
              {[0, 1].map((col) => (
                <View
                  key={col}
                  style={{ width: px(7), height: px(4), borderRadius: px(2), background: color }}
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
              width: px(18),
              height: px(13),
              borderWidth: px(2),
              borderStyle: 'solid',
              borderTopWidth: 0,
              borderBottomLeftRadius: px(7),
              borderBottomRightRadius: px(7),
              ...base,
            }}
          />
          <View
            style={{
              width: px(10),
              height: px(8),
              borderWidth: px(2),
              borderStyle: 'solid',
              borderBottomWidth: 0,
              borderTopLeftRadius: px(6),
              borderTopRightRadius: px(6),
              position: 'absolute',
              /* 提手锚在图标盒顶部正中: 只给 top 不给 left 会退到 .tabbar, 提手会飞到胶囊条顶端 */
              top: 0,
              left: '50%',
              transform: 'translateX(-50%)',
              ...base,
            }}
          />
        </View>
      )
    case 'box':
      return (
        <View className="tabbar__icon" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <View style={{ width: px(18), height: px(12), borderWidth: px(2), borderStyle: 'solid', borderRadius: px(4), ...base }} />
          <View style={{ width: px(10), height: px(2), borderRadius: px(1), background: color, marginTop: px(4) }} />
        </View>
      )
    default:
      return (
        <View className="tabbar__icon" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <View style={{ width: px(17), height: px(17), borderWidth: px(2), borderStyle: 'solid', borderRadius: px(9), ...base }} />
          <View
            style={{
              width: px(5),
              height: px(5),
              borderRadius: px(3),
              background: color,
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
            }}
          />
        </View>
      )
  }
}

export default class CustomTabBar extends Component<Record<string, never>, { selected: number }> {
  state = { selected: 0 }
  private unsubscribeTheme: (() => void) | null = null

  componentDidMount() {
    // 主题切换时强制重渲染: 颜色由 var(--color-ink) 提供, Taro h5/react-native 都
    // 不会自动重渲染 View, 主动触发一次让样式重新求值
    this.unsubscribeTheme = subscribeTheme(() => this.forceUpdate())
  }

  componentWillUnmount() {
    this.unsubscribeTheme?.()
    this.unsubscribeTheme = null
  }

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
    // 自己当变量宿主: 不在页面 .theme-root 里, 不挂就拿不到当前主题的 --color-*
    const themeHost = `theme-vars theme-${getApplied()}`
    return (
      <View className={`tabbar ${themeHost}`}>
        {TABS.map((tab, index) => {
          const on = index === selected
          return (
            <View
              key={tab.pagePath}
              className={cx('tabbar__item', 'tap', on && 'tabbar__item--on')}
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
