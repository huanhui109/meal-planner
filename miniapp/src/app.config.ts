export default defineAppConfig({
  // ⚠ pages[0] 就是小程序的启动页。之前 onboarding 排在第一位, 而它自己又不判断
  //   "是不是老用户", 导致已完成引导的用户每次冷启动都要重走一遍 3 步引导。
  //   改成 today 打头: 新用户由 today 的 useDidShow 按「我的 → 用户信息」里的
  //   引导开关决定是否 reLaunch 到 onboarding, 老用户直接进首页。
  entryPagePath: 'pages/today/index',
  pages: [
    'pages/today/index',
    'pages/onboarding/index',
    'pages/menu/index',
    'pages/shopping/index',
    'pages/fridge/index',
    'pages/profile/index',
    'pages/login/index',
    'pages/about/index',
    'pages/update/index',
    'pages/recipe-detail/index',
    'pages/menu-history/index',
    'pages/invite/index',
    'pages/fandecide/index',
  ],
  window: {
    backgroundTextStyle: 'dark',
    navigationStyle: 'custom',
    // 背景交给 page CSS 接管, 不写死 #e9e9ee —— 深色模式下避免下拉刷新闪冷灰 (audit B3)
    navigationBarTitleText: '饭决',
    navigationBarTextStyle: 'black',
  },
  // 自定义 TabBar: 悬浮毛玻璃胶囊 (参考稿样式), 原生 tabBar 做不出这个效果。
  // 有 custom: true 时 iconPath 可以不配, 图标画在 custom-tab-bar 里。
  tabBar: {
    custom: true,
    color: '#8e8e93',
    selectedColor: '#1c1c1e',
    // custom: true 时原生 tabBar 不渲染, 此值基本不生效; 与 DEFAULT_THEME='cream' 对齐,
    // 避免万一回退到原生 tabBar 时在深色主题下闪白
    backgroundColor: '#FBF9F4',
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
