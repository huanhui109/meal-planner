import type { DecideDish } from '@/types'

// 做法底部弹层: 3-5 步一屏看完, 食材用 chip。点遮罩关闭。
export function StepsSheet({ dish, onClose }: { dish: DecideDish; onClose: () => void }) {
  return (
    <div className="sheet-mask" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-title">{dish.name}</div>
        <div className="sheet-sub">
          {dish.cook_minutes ? `${dish.cook_minutes} 分钟 · ` : ''}
          {dish.steps.length} 步
        </div>
        <ol className="steps">
          {dish.steps.map((s, i) => (
            <li key={i}>
              <span className="step-no">{i + 1}</span>
              <span>{s}</span>
            </li>
          ))}
        </ol>
        {dish.ingredients.length ? (
          <div className="ing-row">
            {dish.ingredients.map((g) => (
              <span className="ing" key={g}>
                {g}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}
