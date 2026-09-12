/**
 * 菜谱详情 (audit T3.2) - 食材清单 / 做法步骤 / 营养 / 标记已做
 *
 * 数据来源: 上一页通过 eventChannel 或 url query 传入, 不走网络
 *  (menu / today 页已把完整 recipe (含 steps / ingredients) 拉下来了)
 */
import { useState } from 'react'
import Taro, { useRouter } from '@tarojs/taro'
import { Text, View } from '@tarojs/components'

import { formatMoney } from '@shared/format'
import { mealLabel } from '@shared/labels'

import { Bar, Card, Chip, PageHead, PillButton } from '../../components/ui'
import { markCooked } from '../../lib/meal-actions'
import { toast } from '../../lib/nav'
import { track } from '../../lib/events'

interface RecipePayload {
  meal_id: number
  menu_id: number
  meal_type: string
  name: string
  steps: string | null
  cuisine: string | null
  difficulty: number | null
  cook_minutes: number | null
  calories: number | null
  protein_g: number | null
  carb_g: number | null
  fat_g: number | null
  estimated_cost: number | null
  is_cooked: boolean
  ingredients: Array<{
    name: string
    quantity: number | null
    unit: string | null
  }>
}

export default function RecipeDetailPage() {
  const router = useRouter<{ data?: string }>()
  const [recipe, setRecipe] = useState<RecipePayload | null>(() => {
    try {
      const raw = router.params.data
      if (!raw) return null
      return JSON.parse(decodeURIComponent(raw)) as RecipePayload
    } catch {
      return null
    }
  })
  const [busy, setBusy] = useState(false)

  if (!recipe) {
    return (
      <View className="page">
        <PageHead title="菜谱详情" subtitle="数据加载失败" />
        <Card>
          <View className="card__hint">没有找到这道菜的信息, 请返回重试</View>
        </Card>
      </View>
    )
  }

  const steps = (recipe.steps || '')
    .split(/[\n;；。]+/)
    .map((s) => s.trim())
    .filter(Boolean)

  const handleCook = async () => {
    if (recipe.is_cooked) return
    setBusy(true)
    try {
      const ok = await markCooked({ id: recipe.menu_id } as never, recipe.meal_id)
      if (ok) {
        toast('已标记, 库存已扣减', 'success')
        setRecipe({ ...recipe, is_cooked: true })
        track('mark_cooked', { menu_id: recipe.menu_id, item_id: recipe.meal_id, source: 'detail' })
      }
    } catch (err) {
      toast((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const macroTotal =
    (recipe.protein_g ?? 0) * 4 + (recipe.carb_g ?? 0) * 4 + (recipe.fat_g ?? 0) * 9 || 0

  return (
    <View className="page">
      <PageHead title={recipe.name} subtitle={`${mealLabel(recipe.meal_type)} · ${recipe.cuisine || '家常'}`} />

      <Card>
        <View style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {recipe.cook_minutes ? <Chip>约 {recipe.cook_minutes} 分钟</Chip> : null}
          {recipe.difficulty ? <Chip>难度 {recipe.difficulty}/5</Chip> : null}
          {recipe.calories ? <Chip>{recipe.calories} kcal</Chip> : null}
          {recipe.estimated_cost ? <Chip tone="accent">{formatMoney(recipe.estimated_cost)}</Chip> : null}
          {recipe.is_cooked ? <Chip tone="accent">已做过</Chip> : null}
        </View>
      </Card>

      {macroTotal > 0 ? (
        <Card>
          <Text className="card__label">三大营养素占比</Text>
          <View style={{ marginTop: 10 }}>
            <View className="macro-row">
              <Text className="macro-row__key">蛋白质</Text>
              <Bar value={((recipe.protein_g ?? 0) * 4 * 100) / macroTotal} tone="accent" />
              <Text className="macro-row__val">{recipe.protein_g ?? 0} g</Text>
            </View>
            <View className="macro-row">
              <Text className="macro-row__key">碳水</Text>
              <Bar value={((recipe.carb_g ?? 0) * 4 * 100) / macroTotal} tone="ink" />
              <Text className="macro-row__val">{recipe.carb_g ?? 0} g</Text>
            </View>
            <View className="macro-row">
              <Text className="macro-row__key">脂肪</Text>
              <Bar value={((recipe.fat_g ?? 0) * 9 * 100) / macroTotal} tone="warn" />
              <Text className="macro-row__val">{recipe.fat_g ?? 0} g</Text>
            </View>
          </View>
        </Card>
      ) : null}

      <Card>
        <Text className="card__label">食材 ({recipe.ingredients.length})</Text>
        <View style={{ marginTop: 10 }}>
          {recipe.ingredients.map((ing, i) => (
            <View key={i} className="ing-row">
              <Text className="ing-row__name">{ing.name}</Text>
              <Text className="ing-row__qty">
                {ing.quantity ?? ''}
                {ing.unit || ''}
              </Text>
            </View>
          ))}
        </View>
      </Card>

      <Card>
        <Text className="card__label">做法</Text>
        <View style={{ marginTop: 10 }}>
          {steps.length > 0 ? (
            steps.map((step, i) => (
              <View key={i} className="step-row">
                <Text className="step-row__num">{i + 1}</Text>
                <Text className="step-row__text">{step}</Text>
              </View>
            ))
          ) : (
            <View className="card__hint">这道菜还没有录入详细步骤</View>
          )}
        </View>
      </Card>

      <View style={{ marginTop: 16 }}>
        <PillButton
          block
          disabled={busy || recipe.is_cooked}
          onClick={handleCook}
        >
          {recipe.is_cooked ? '已经做过了' : busy ? '处理中…' : '标记已做 (扣库存)'}
        </PillButton>
      </View>

      <View style={{ height: 24 }} />
    </View>
  )
}
