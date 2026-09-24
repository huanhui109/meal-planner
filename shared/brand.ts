/**
 * 品牌文案 - H5 与小程序唯一的名称来源
 *
 * 改名字只需要改这里 + config/default.yaml, 两端界面、标题、分享文案
 * 全部从这一处取, 不会出现"H5 叫这个、小程序叫那个"的情况。
 * Logo 源文件在 assets/logo/ (由 scripts/gen_logo.mjs 生成)。
 */
export const brand = {
  /** 短名: TabBar、导航、面包屑等窄空间用 */
  name: '饭决',
  /** 全名: 登录页、文档、小程序 navigationBarTitleText */
  fullName: '饭决 FAN·DECIDE',
  /** 副标: 跟在短名后面的一行小字 */
  subtitle: '今天吃啥，交给饭决',
  /** 一句话价值主张, 登录页与空状态、启动页 Slogan 用 */
  slogan: '今天吃啥，交给饭决',
  description: '纠结吃什么的每一秒都在浪费人生。饭决替你决定这一餐。',
  /** 用户反复换菜时的品牌语气提示 (需求 4) */
  stubbornLine: '别纠结了，我替你倔一回。',
  /** 首页唯一主按钮文案 (需求 4) */
  decideAction: '饭决',
  /** 离线兜底结果卡的角标文案 (需求 7) */
  offlineBadge: '本地答案',
  /** 我的页脚注 */
  localDataNote: '数据仅存储在本地 · 不向云端发送个人身份信息',
} as const

export type Brand = typeof brand

export default brand
