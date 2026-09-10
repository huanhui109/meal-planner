/**
 * 品牌文案 - H5 与小程序唯一的名称来源
 *
 * 改名字只需要改这里 + config/default.yaml, 两端界面、标题、分享文案
 * 全部从这一处取, 不会出现"H5 叫这个、小程序叫那个"的情况。
 * Logo 源文件在 assets/logo/ (由 scripts/gen_logo.mjs 生成)。
 */
export const brand = {
  /** 短名: TabBar、导航、面包屑等窄空间用 */
  name: '每周鲜',
  /** 全名: 登录页、文档、小程序 navigationBarTitleText */
  fullName: '每周鲜 · AI 营养菜谱',
  /** 副标: 跟在短名后面的一行小字 */
  subtitle: 'AI 营养菜谱',
  /** 一句话价值主张, 登录页与空状态用 */
  slogan: '一周的饭, 一次安排好',
  description:
    '按你的偏好生成一周营养菜谱, 算好营养与预算; 缺什么直接补单, 做完自动扣库存。',
  /** 我的页脚注 */
  localDataNote: '数据仅存储在本地 · 不向云端发送个人身份信息',
} as const

export type Brand = typeof brand

export default brand
