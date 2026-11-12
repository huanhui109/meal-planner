import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Alert, Modal, Skeleton, message } from 'antd'
import {
  ArrowRightOutlined, CheckOutlined, ClockCircleOutlined, ControlOutlined,
  CopyOutlined, ExportOutlined, LoadingOutlined, ReloadOutlined, SwapOutlined, TeamOutlined,
  ThunderboltOutlined, UndoOutlined,
} from '@ant-design/icons'
import { adjustmentLabel, mealSlotLabels, type MealDish, type MealSlotName } from '@shared/meal'
import { useMeal } from '../../hooks/useMeal'
import { useMealAssistant } from '../../hooks/useMealAssistant'
import { copyText } from '../../lib/clipboard'
import MealConditions from '../../components/MealConditions'
import MealAssistantDialog from '../../components/MealAssistantDialog'

const roleLabel = { complete: '主食餐', main: '主菜', side: '蔬菜', staple: '主食', soup: '汤' }
const dishImages: Record<string, string> = {
  米饭: '/food/rice.webp',
  番茄鸡蛋面: '/food/tomato-noodles.webp',
  西红柿鸡蛋挂面: '/food/tomato-noodles.webp',
  西红柿鸡蛋面: '/food/tomato-noodles.webp',
}

export default function Meal() {
  const [params, setParams] = useSearchParams()
  const rawSlot = params.get('slot')
  const slot = rawSlot && rawSlot in mealSlotLabels ? rawSlot as MealSlotName : undefined
  const date = params.get('date') || undefined
  const { view, loading, busy: mealBusy, error, refresh, propose, act } = useMeal(slot, date)
  const ai = useMealAssistant(view, refresh)
  const busy = mealBusy || ai.pending
  const [conditions, setConditions] = useState(false)
  const [assistant, setAssistant] = useState(false)
  const [deduct, setDeduct] = useState(false)
  const [copyFallback, setCopyFallback] = useState('')
  const proposal = view?.proposal
  useEffect(() => { setDeduct(false) }, [proposal?.id])
  const selected = proposal?.status === 'accepted' || proposal?.status === 'eaten'
  const eaten = proposal?.status === 'eaten'
  const context = view?.context
  const label = context ? mealSlotLabels[context.meal_slot] : '这一餐'
  const copy = async (text: string) => {
    if (await copyText(text)) message.success('已复制')
    else setCopyFallback(text)
  }

  return (
    <div className="meal-page">
      <header className="meal-page-heading">
        <div>
          <div className="meal-eyebrow">{context ? new Date(`${context.meal_date}T12:00:00`).toLocaleDateString('zh-CN', {
            month: 'long', day: 'numeric', weekday: 'long',
          }) : '今天'}</div>
          <h1>{eaten ? '这一餐，吃好了。' : selected ? '好，就吃这一餐。' : `${label}，这样吃。`}</h1>
        </div>
        <select aria-label="切换餐次" value={context?.meal_slot ?? slot ?? 'dinner'} disabled={loading || busy}
          onChange={(event) => setParams({ slot: event.target.value, ...(date ? { date } : {}) })}>
          {Object.entries(mealSlotLabels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
        </select>
      </header>

      <div className="meal-toolbar">
        <div className="meal-segments" role="group" aria-label="用餐方式">
          {([['auto', '帮我定'], ['cook', '自己做'], ['takeout', '点外卖']] as const).map(([mode, text]) =>
            <button type="button" key={mode} aria-pressed={context?.mode === mode}
              className={context?.mode === mode ? 'active' : ''} disabled={!view || busy || eaten}
              onClick={() => { void propose({ mode }) }}>{text}</button>)}
        </div>
        <button type="button" className="meal-button meal-quiet" disabled={!view || busy || eaten}
          onClick={() => setConditions(true)}><ControlOutlined />改条件</button>
      </div>

      {ai.pending && <div className="meal-ai-pending" role="status" aria-live="polite">
        <LoadingOutlined /><span>{ai.uncertain ? 'AI 调整的发送状态待确认' : adjustmentLabel(ai.job)}</span>
        <button type="button" className="meal-text-link" onClick={() => setAssistant(true)}>查看进度<ArrowRightOutlined /></button>
      </div>}
      {ai.job?.status === 'completed' && ai.job.proposal_id === proposal?.id && <div className="meal-ai-pending">
        <CheckOutlined /><span>AI 已调整这一餐，请确认新方案</span>
      </div>}
      {ai.job?.status === 'failed' && !assistant && <Alert className="meal-alert" type="warning" showIcon
        message={ai.job.error} action={<button type="button" className="meal-text-link"
          onClick={() => setAssistant(true)}>修改要求<ArrowRightOutlined /></button>} />}

      {error && <Alert className="meal-alert" type="warning" showIcon message={error}
        action={<button type="button" className="meal-icon" aria-label="刷新这一餐" title="刷新" disabled={busy}
          onClick={() => { void refresh(!proposal) }}><ReloadOutlined /></button>} />}

      {loading ? <div className="meal-loading" aria-label="正在读取这一餐">
        <Skeleton active paragraph={{ rows: 5 }} />
      </div> : proposal && context ? (
        <div className="meal-workspace" aria-busy={busy}>
          <section className="meal-proposal">
            <div className="meal-provenance">
              <span className={`meal-source ${proposal.source === 'assistant' ? 'ai' : ''}`}>
                <ThunderboltOutlined />{proposal.source === 'assistant' ? 'AI 调整' : '快速推荐'}
              </span>
              <span>{proposal.mode === 'cook' ? '在家吃' : '外卖安排'}</span>
              {selected && <span className="meal-state"><CheckOutlined />{eaten ? '已吃过' : '已选定'}</span>}
            </div>
            <h2 className="meal-title">{proposal.title}</h2>
            <p className="meal-reason">{proposal.reason}</p>
            <div className="meal-facts">
              <span><TeamOutlined />{proposal.servings} 人份</span>
              {proposal.estimated_minutes != null &&
                <span><ClockCircleOutlined />参考用时约 {proposal.estimated_minutes} 分钟</span>}
              {proposal.estimated_cost != null && <span>估算 ¥{proposal.estimated_cost.toFixed(1)}</span>}
              {context.max_spice === 0 && <span>不辣</span>}
              {context.vegetarian && <span>不吃肉</span>}
            </div>

            <div className="meal-dishes">
              {proposal.dishes.map((dish, index) =>
                <Dish key={dish.key} dish={dish} index={index} showSteps={selected && proposal.mode === 'cook'} />)}
            </div>

            <div className="meal-actions">
              {!selected ? (
                <button type="button" className="meal-button meal-primary" disabled={busy}
                  onClick={() => { void act('accept') }}>
                  {busy ? '正在安排…' : '就吃这个'}<ArrowRightOutlined />
                </button>
              ) : !eaten ? (
                <button type="button" className="meal-button meal-primary" disabled={busy}
                  onClick={() => { void act('complete', deduct) }}>
                  <CheckOutlined />{busy ? '正在记下…' : '吃过了，记下来'}
                </button>
              ) : (
                <button type="button" className="meal-button" disabled={busy}
                  onClick={() => { void act('undo') }}><UndoOutlined />撤销吃过记录</button>
              )}
              {!eaten && <button type="button" className="meal-button" disabled={busy}
                onClick={() => { void propose() }}><SwapOutlined />换个方案</button>}
              <button type="button" className="meal-button meal-ai-button" disabled={mealBusy || eaten}
                onClick={() => setAssistant(true)}><ThunderboltOutlined />交给 AI 调整</button>
            </div>
            {selected && !eaten && proposal.mode === 'cook' &&
              <label className="meal-deduct">
                <input type="checkbox" checked={deduct} onChange={(event) => setDeduct(event.target.checked)} disabled={busy} />
                按已知配方用量扣减库存
              </label>}
            {proposal.inventory_result && <div className="meal-receipt" role="status">
              <CheckOutlined /><div>
                <strong>{proposal.inventory_result.note}</strong>
                {proposal.inventory_result.missing.length > 0 &&
                  <p>{proposal.inventory_result.missing.map((line) => line.name).join('、')}库存不足，未扣足</p>}
                {proposal.inventory_result.unquantified.length > 0 &&
                  <p>{proposal.inventory_result.unquantified.join('、')}用量或份数未知，未精确扣减</p>}
              </div>
            </div>}
          </section>

          <aside className="meal-detail">
            <div className="meal-detail-heading">
              <span className="meal-eyebrow">{selected ? '接下来' : '这一餐的准备'}</span>
              <h3>{proposal.mode === 'takeout' ? '把这一餐点好' : proposal.missing.length ? '还需要这些' : '家里基本齐了'}</h3>
            </div>
            {proposal.mode === 'takeout' && proposal.takeout ? (
              <>
                <p className="meal-search-term">{proposal.takeout.search_term}</p>
                <div className="meal-order-note">{proposal.takeout.order_note}</div>
                <div className="meal-detail-actions">
                  <button type="button" className="meal-button" onClick={() => { void copy(proposal.takeout!.order_note) }}>
                    <CopyOutlined />复制点单备注
                  </button>
                  {proposal.takeout.search_url && <a className="meal-button" target="_blank" rel="noopener noreferrer"
                    href={proposal.takeout.search_url}><ExportOutlined />去搜这一餐</a>}
                </div>
              </>
            ) : (
              <>
                <div className="meal-ingredients">
                  {proposal.missing.map((name) => <div key={name}><span>{name}</span><small>家里未记录</small></div>)}
                  {proposal.available.map((name) => <div key={name} className="owned"><span>{name}</span><small><CheckOutlined />已记录</small></div>)}
                </div>
                <div className="meal-detail-actions">
                  <button type="button" className="meal-button" onClick={() => {
                    void copy(`${proposal.title}\n${proposal.servings} 人份\n待确认或采购：${proposal.missing.join('、')}`)
                  }}><CopyOutlined />复制食材清单</button>
                  <Link className="meal-text-link" to="/kitchen">查看厨房<ArrowRightOutlined /></Link>
                </div>
              </>
            )}
            {proposal.assistant_note && <div className="meal-assistant-note">
              <ThunderboltOutlined /><div><strong>AI 的搭配建议</strong><p>{proposal.assistant_note}</p></div>
            </div>}
            <div className="meal-notes">
              {proposal.protected_avoid.length > 0 && <p>已避开：{proposal.protected_avoid.join('、')}</p>}
              {proposal.warnings.map((warning) => <p key={warning}>{warning}</p>)}
              {proposal.mode === 'cook' && <p>“家里已有”仅按记录名称匹配，请确认实际余量。</p>}
            </div>
          </aside>
        </div>
      ) : (
        <section className="meal-empty">
          <div className="meal-empty-mark"><img src="/logo-mark.svg" alt="" width="56" height="56" /></div>
          <h2>{busy ? '正在替你安排这一餐' : '还没有合适的安排'}</h2>
          <p>{busy ? '先看看口味和用餐条件。' : '保留你的要求，再试一个新的组合。'}</p>
          <div className="meal-actions">
            <button type="button" className="meal-button meal-primary" disabled={busy || !view}
              onClick={() => { void propose() }}>帮我决定<ArrowRightOutlined /></button>
            <button type="button" className="meal-button" disabled={!context || busy}
              onClick={() => setConditions(true)}><ControlOutlined />改条件</button>
            <button type="button" className="meal-button meal-ai-button" disabled={!view || mealBusy}
              onClick={() => setAssistant(true)}><ThunderboltOutlined />交给 AI 调整</button>
            {!view && <>
              <button type="button" className="meal-button" onClick={() => { void refresh(true) }}><ReloadOutlined />重新连接</button>
              {(date || slot) && <Link to="/" className="meal-button">回到当前餐次</Link>}
            </>}
            <Link to="/preferences" className="meal-text-link">查看长期忌口<ArrowRightOutlined /></Link>
          </div>
        </section>
      )}
      {context && <MealConditions open={conditions} context={context} busy={busy} error={error}
        onClose={() => setConditions(false)} onApply={propose} />}
      <Modal open={Boolean(copyFallback)} title="复制内容" footer={null} onCancel={() => setCopyFallback('')}>
        <div className="meal-assistant-dialog"><textarea aria-label="待复制内容" readOnly value={copyFallback} rows={8} /></div>
      </Modal>
      {view && <MealAssistantDialog open={assistant} onClose={() => setAssistant(false)}
        view={view} assistant={ai} onCopy={copy} />}
    </div>
  )
}

function Dish({ dish, index, showSteps }: { dish: MealDish; index: number; showSteps: boolean }) {
  return (
    <article className={`meal-dish ${showSteps ? 'expanded' : ''}`}>
      <span className="meal-dish-number">{String(index + 1).padStart(2, '0')}</span>
      <div className="meal-dish-content">
        <div className="meal-dish-heading"><h3>{dish.name}</h3><span>{roleLabel[dish.role]}</span></div>
        <p className="meal-dish-ingredients">{dish.ingredients.map((name) => {
          const line = dish.requirements.find((item) => item.name === name)
          return line?.quantity != null ? `${name} ${line.quantity}${line.unit}` : name
        }).join(' / ')}</p>
        {showSteps && <ol className="meal-steps">
          {dish.steps.map((step, n) => <li key={`${n}-${step}`}>{step}</li>)}
        </ol>}
      </div>
      {dishImages[dish.name] && <img className="meal-dish-image" src={dishImages[dish.name]}
        alt={`${dish.name}实物示意`} title="图片来源：HowToCook，菜品实物示意" loading="lazy" width="84" height="84" />}
    </article>
  )
}
