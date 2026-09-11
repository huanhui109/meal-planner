"""开源菜谱导入 - 抓取、归一化、生成 SQL、落库

数据来源:
  * ``proj.kitchen`` (https://proj.kitchen/api) - 结构化 JSON, MIT
  * ``HowToCook`` (https://github.com/Anduin2017/HowToCook) - markdown 菜谱, Unlicense

两源按菜名去重合并, 统一的字段语义见 ``normalize.RecipeRecord``。
"""
