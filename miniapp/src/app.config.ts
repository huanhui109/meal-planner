export default defineAppConfig({
  pages: [
    'pages/today/index',
    'pages/menu/index',
    'pages/shopping/index',
    'pages/fridge/index',
    'pages/profile/index',
    'pages/login/index',
  ],
  window: {
    backgroundTextStyle: 'dark',
    navigationStyle: 'custom',
    // 背景交给 page CSS 接管, 不写死 #e9e9ee —— 深色模式下避免下拉刷新闪冷灰 (audit B3)
    navigationBarTitleText: '每周鲜',
    navigationBarTextStyle: 'black',
  },
  // 自定义 TabBar: 悬浮毛玻璃胶囊 (参考稿样式), 原生 tabBar 做不出这个效果。
  // 有 custom: true 时 iconPath 可以不配, 图标画在 custom-tab-bar 里。
  tabBar: {
    custom: true,
    color: '#8e8e93',
    selectedColor: '#1c1c1e',
    backgroundColor: '#ffffff',
    borderStyle: 'white',
    // 4 Tab: 今日 / 周菜单 / 采购 / 冰箱 —— 「我的」从 TabBar 移出, 走今日页右上角头像
    list: [
      { pagePath: 'pages/today/index', text: '今日' },
      { pagePath: 'pages/menu/index', text: '周菜单' },
      { pagePath: 'pages/shopping/index', text: '采购' },
      { pagePath: 'pages/fridge/index', text: '冰箱' },
    ],
  },
})
