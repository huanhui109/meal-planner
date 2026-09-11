export default {
  component: true,
  /**
   * 样式隔离是这里唯一的坑: 小程序的自定义组件默认 styleIsolation = 'isolated',
   * 此时 app.wxss 里的**类选择器不会作用到组件内部**, 于是 .tabbar / .tabbar__item
   * 这些规则全部失效 —— TabBar 会退化成没有样式的普通流式布局 (标签竖排、图标散落),
   * 也就是"菜单错位、无法使用"的真正原因。
   * apply-shared: 页面/全局样式可以影响组件, 组件样式不外泄。
   */
  styleIsolation: 'apply-shared',
}
