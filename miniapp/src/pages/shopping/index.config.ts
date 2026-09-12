export default definePageConfig({
  navigationBarTitleText: '采购清单',
  navigationStyle: 'custom',
  // 编译期静态默认值 (DEFAULT_THEME='cream'), 运行期由 applyTheme 覆盖 (audit B3)
  backgroundColor: '#FBF9F4',
  backgroundColorTop: '#FBF9F4',
  backgroundColorBottom: '#FBF9F4',
  enablePullDownRefresh: true,
})
