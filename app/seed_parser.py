"""
从「牧场饲养攻略.md」解析物种信息和每日喂养计划。
文档格式约定：
  - 每个物种以 `### N、物种名` 开头
  - 紧跟一行描述：「xxx的初始饱食度为N，每2天减少N点饱食度。幼年期N天，成年期N天，最大可延长寿命N天」
  - 随后是标准 Markdown 表格：|阶段|天数|初始饱食度|喂养饲料|结算饱食度|产出|
"""

import os
import re

# markdown 中无 emoji，在此维护映射；新增物种时补充即可
_EMOJI_MAP: dict[str, str] = {
    "熊猫":     "🐼",
    "娃娃鱼":   "🦎",
    "鳄鱼":     "🐊",
    "豹子":     "🐆",
    "金刚鹦鹉": "🦜",
}

_DEFAULT_MD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "牧场饲养攻略.md",
)

# 描述行正则
_DESC_RE = re.compile(
    r"初始饱食度[为是](\d+)[，,].*?每2天减少(\d+)点.*?幼年期(\d+)天[，,。].*?成年期(\d+)天[，,。].*?最大可延长寿命(\d+)天"
)

# 表格数据行正则（跳过表头和分隔行）
_ROW_RE = re.compile(
    r"^\|\s*([^|\-][^|]*?)\s*\|\s*(\d+)\s*\|\s*(\d*)\s*\|\s*(\d*)\s*\|\s*(\d*)\s*\|\s*([^|]*?)\s*\|"
)


def parse_feeding_guide(md_path: str = _DEFAULT_MD) -> list[dict]:
    """解析 markdown 文件，返回物种配置列表。"""
    with open(md_path, encoding="utf-8") as f:
        content = f.read()

    # 按 ### N、xxx 切分章节，跳过文件开头（前提说明）
    sections = re.split(r"\n###\s+\d+[、.]\s*", content)[1:]

    result: list[dict] = []
    for section in sections:
        lines = section.strip().splitlines()
        if not lines:
            continue

        name = lines[0].strip()
        body = "\n".join(lines[1:])

        # ── 解析描述行 ──────────────────────────────────────────
        m = _DESC_RE.search(body)
        if not m:
            continue
        initial_satiety = int(m.group(1))
        decay           = int(m.group(2))
        juvenile_days   = int(m.group(3))
        adult_days      = int(m.group(4))
        max_extra       = int(m.group(5))

        # ── 解析表格 ─────────────────────────────────────────────
        schedule: dict[int, dict] = {}
        for line in body.splitlines():
            row = _ROW_RE.match(line.strip())
            if not row:
                continue
            stage = row.group(1).strip()
            day   = int(row.group(2))

            satiety_start = int(row.group(3)) if row.group(3).strip() else 0
            feed          = int(row.group(4)) if row.group(4).strip() else 0
            satiety_end   = int(row.group(5)) if row.group(5).strip() else satiety_start

            # 产出可能是 "360+100" 这样的格式，取数字之和
            output_str = row.group(6).strip()
            output = sum(int(n) for n in re.findall(r"\d+", output_str)) if output_str else 0

            schedule[day] = {
                "stage":         stage,
                "satiety_start": satiety_start,
                "feed":          feed,
                "satiety_end":   satiety_end,
                "output":        output,
            }

        if not schedule:
            continue

        result.append({
            "key":             name,           # 直接用中文名作为主键
            "name":            name,
            "emoji":           _EMOJI_MAP.get(name, "🐾"),
            "initial_satiety": initial_satiety,
            "decay_per_2days": decay,
            "juvenile_days":   juvenile_days,
            "adult_days":      adult_days,
            "max_extra_days":  max_extra,
            "total_days":      max(schedule.keys()),
            "schedule":        schedule,
        })

    return result
