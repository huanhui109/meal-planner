export default definePageConfig({
  navigationBarTitleText: '首页',
  navigationStyle: 'custom',
  // 编译期静态默认值, 取 DEFAULT_THEME='cream' 的主背景; 实际颜色由 lib/theme.ts
  // 的 applyTheme 在运行期用 Taro.setBackgroundColor 覆盖 (audit B3)。
  backgroundColor: '#FBF9F4',
  backgroundColorTop: '#FBF9F4',
  backgroundColorBottom: '#FBF9F4',
  enablePullDownRefresh: true,
})
