import type { CSSProperties } from 'react'

// 内联 SVG 图标集 —— 不引任何图标库, 决策屏要的就这么几个。
// 全部 24x24, stroke 跟随 currentColor, 所以颜色由 CSS 控制。

type P = { size?: number; style?: CSSProperties; className?: string }

function base(size = 22) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
}

export const ClockIcon = ({ size, style, className }: P) => (
  <svg {...base(size)} style={style} className={className} aria-hidden>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
)

export const FlameIcon = ({ size, style, className }: P) => (
  <svg {...base(size)} style={style} className={className} aria-hidden>
    <path d="M12 3c1 3-2 4-2 7a2 2 0 0 0 4 0c0-1 0-1 0-1 2 1 3 3 3 5a5 5 0 0 1-10 0c0-4 3-6 5-11z" />
  </svg>
)

export const TagIcon = ({ size, style, className }: P) => (
  <svg {...base(size)} style={style} className={className} aria-hidden>
    <path d="M4 4h7l9 9-7 7-9-9z" />
    <circle cx="8.5" cy="8.5" r="1.4" />
  </svg>
)

export const SparkIcon = ({ size, style, className }: P) => (
  <svg {...base(size)} style={style} className={className} aria-hidden>
    <path d="M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z" />
  </svg>
)

export const SunIcon = ({ size, style, className }: P) => (
  <svg {...base(size)} style={style} className={className} aria-hidden>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" />
  </svg>
)

export const RainIcon = ({ size, style, className }: P) => (
  <svg {...base(size)} style={style} className={className} aria-hidden>
    <path d="M7 14a4 4 0 0 1 .5-8 5 5 0 0 1 9.5 1.5A3.5 3.5 0 0 1 17 14" />
    <path d="M8 18l-1 2M12 18l-1 2M16 18l-1 2" />
  </svg>
)

export const SnowIcon = ({ size, style, className }: P) => (
  <svg {...base(size)} style={style} className={className} aria-hidden>
    <path d="M12 2v20M4 7l16 10M20 7L4 17" />
  </svg>
)
