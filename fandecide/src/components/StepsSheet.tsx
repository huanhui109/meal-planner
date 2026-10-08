// 做法底部弹层: 步骤 + 食材一屏看完, 点遮罩或关闭按钮收起。
// 给 today 的结果卡和周菜单的菜品复用同一套。

export interface SheetIngredient {
  name: string
  quantity?: number | null
  unit?: string
}

export function StepsSheet({
  title,
  steps,
  ingredients,
  onClose,
}: {
  title: string
  steps: string[]
  ingredients?: SheetIngredient[]
  onClose: () => void
}) {
  return (
    <div className="sheet-mask" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grab" />
        <div className="sheet-title">{title}</div>
        <div className="sheet-sub">
          {steps.length} 步{ingredients && ingredients.length ? ` · ${ingredients.length} 样食材` : ''}
        </div>
        <ol className="steps">
          {steps.map((s, i) => (
            <li key={i}>
              <i>{i + 1}</i>
              <span>{s}</span>
            </li>
          ))}
        </ol>
        {ingredients && ingredients.length ? (
          <div className="ing-row">
            {ingredients.map((g, i) => (
              <span className="ing" key={i}>
                {g.name}
                {g.quantity ? ` ${g.quantity}${g.unit || ''}` : ''}
              </span>
            ))}
          </div>
        ) : null}
        <button className="button primary" style={{ width: '100%', marginTop: 18 }} onClick={onClose}>
          知道了
        </button>
      </div>
    </div>
  )
}
