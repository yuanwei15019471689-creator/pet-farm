from datetime import date, datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
import aiomysql

from .database import get_db

router = APIRouter(prefix="/api")


# ── 请求模型 ───────────────────────────────────────────────────────────────────

from pydantic import BaseModel

class AnimalCreate(BaseModel):
    nickname: str = ""
    species: str
    start_date: str  # YYYY-MM-DD


class FeedRequest(BaseModel):
    feed_date: str | None = None  # 默认今天


# ── DB 工具函数 ────────────────────────────────────────────────────────────────

async def _get_species_cfg(db: Any, species_key: str) -> dict | None:
    """从 DB 读取物种基本信息"""
    async with db.cursor() as cur:
        await cur.execute("SELECT * FROM species WHERE `key` = %s", (species_key,))
        row = await cur.fetchone()
    return row


async def _get_schedule_row(db: Any, species_key: str, day: int) -> dict | None:
    """从 DB 读取指定物种指定天的喂养计划"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT * FROM feeding_schedule WHERE species_key = %s AND day = %s",
            (species_key, day)
        )
        row = await cur.fetchone()
    return row


def _calc_day(start_date_str: str, target: date | None = None) -> int:
    start = date.fromisoformat(start_date_str)
    return ((target or date.today()) - start).days + 1


async def _build_status(db: Any, row: dict, today: date | None = None) -> dict:
    """根据动物记录 + DB 计划数据计算今日状态"""
    today = today or date.today()
    cfg = await _get_species_cfg(db, row["species"])
    if not cfg:
        return {}

    day = _calc_day(row["start_date"], today)
    total_days = cfg["total_days"] + row["extra_days"]

    fed_today, fed_amount = False, 0

    if day < 1:
        stage, feed_needed, output, is_alive = "未开始", 0, 0, False
        satiety = row.get("current_satiety") or cfg["initial_satiety"]
    elif day > total_days:
        stage, feed_needed, output, is_alive = "已到期", 0, 0, False
        satiety = row.get("current_satiety") or 0
    else:
        sched = await _get_schedule_row(db, row["species"], day)
        if sched:
            stage       = sched["stage"]
            feed_needed = sched["feed_amount"]
            output      = sched["output"]
        else:
            stage, feed_needed, output = "成年期", 0, 0

        # 根据今天是否已喂养决定显示饱食度：
        # 未喂 → 计划表当天 satiety_start（已含2天自然衰减）
        # 已喂 → 计划表当天 satiety_end
        async with db.cursor() as cur:
            await cur.execute(
                "SELECT amount FROM feed_logs WHERE animal_id = %s AND feed_date = %s",
                (row["id"], today.isoformat())
            )
            fed_row = await cur.fetchone()
        if fed_row:
            satiety = sched["satiety_end"] if sched else row.get("current_satiety")
        else:
            satiety = sched["satiety_start"] if sched else (row.get("current_satiety") or cfg["initial_satiety"])
        is_alive = True
        fed_today = bool(fed_row)
        fed_amount = fed_row["amount"] if fed_row else 0

    progress = min(100, round(day / max(total_days, 1) * 100)) if day >= 1 else 0

    created_at = row["created_at"]
    if isinstance(created_at, datetime):
        created_at = created_at.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "id":           row["id"],
        "nickname":     row["nickname"],
        "species":      row["species"],
        "species_name": cfg["name"],
        "emoji":        cfg["emoji"],
        "start_date":   row["start_date"],
        "extra_days":   row["extra_days"],
        "sold_at":      row["sold_at"],
        "day":          day,
        "total_days":   total_days,
        "stage":        stage,
        "satiety":      satiety,
        "feed_needed":  feed_needed,
        "output_today": output,
        "is_alive":     is_alive,
        "progress":     progress,
        "created_at":   created_at,
        "fed_today":    fed_today if is_alive else False,
        "fed_amount":   fed_amount if is_alive else 0,
    }


# ── 接口 ───────────────────────────────────────────────────────────────────────

@router.get("/animals")
async def list_animals(db: Any = Depends(get_db)):
    today = date.today()
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT * FROM animals WHERE sold_at IS NULL ORDER BY start_date DESC, id DESC"
        )
        rows = await cur.fetchall()

    result = []
    for row in rows:
        status = await _build_status(db, row, today)
        result.append(status)

    return result


@router.post("/animals")
async def create_animal(body: AnimalCreate, db: Any = Depends(get_db)):
    cfg = await _get_species_cfg(db, body.species)
    if not cfg:
        raise HTTPException(status_code=400, detail="不支持的动物种类")
    try:
        start = date.fromisoformat(body.start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")

    # 昵称为空时自动生成：物种名称 + 开始日期，例如 "熊猫20260311"
    nickname = body.nickname.strip() or (cfg["name"] + start.strftime("%Y%m%d"))

    # 初始饱食度取计划表第1天的 satiety_start
    sched_day1 = await _get_schedule_row(db, body.species, 1)
    init_satiety = sched_day1["satiety_start"] if sched_day1 else cfg["initial_satiety"]

    async with db.cursor() as cur:
        await cur.execute(
            "INSERT INTO animals (nickname, species, start_date, current_satiety) VALUES (%s, %s, %s, %s)",
            (nickname, body.species, body.start_date, init_satiety)
        )
        new_id = cur.lastrowid
    await db.commit()

    async with db.cursor() as cur:
        await cur.execute("SELECT * FROM animals WHERE id = %s", (new_id,))
        row = await cur.fetchone()
    return await _build_status(db, row)


@router.delete("/animals/{animal_id}")
async def delete_animal(animal_id: int, db: Any = Depends(get_db)):
    async with db.cursor() as cur:
        await cur.execute("SELECT id FROM animals WHERE id = %s", (animal_id,))
        if not await cur.fetchone():
            raise HTTPException(status_code=404, detail="动物不存在")
    async with db.cursor() as cur:
        await cur.execute("DELETE FROM animals WHERE id = %s", (animal_id,))
    await db.commit()
    return {"ok": True}


@router.post("/animals/{animal_id}/sell")
async def sell_animal(animal_id: int, db: Any = Depends(get_db)):
    """逻辑删除：标记为已售出，前端不再展示"""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id, sold_at FROM animals WHERE id = %s", (animal_id,)
        )
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="动物不存在")
    if row["sold_at"]:
        raise HTTPException(status_code=400, detail="该动物已售出")

    sold_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE animals SET sold_at = %s WHERE id = %s",
            (sold_at, animal_id)
        )
    await db.commit()
    return {"ok": True, "sold_at": sold_at}


@router.post("/animals/{animal_id}/feed")
async def feed_animal(animal_id: int, body: FeedRequest, db: Any = Depends(get_db)):
    async with db.cursor() as cur:
        await cur.execute("SELECT * FROM animals WHERE id = %s", (animal_id,))
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="动物不存在")

    feed_date = body.feed_date or date.today().isoformat()
    day = _calc_day(row["start_date"], date.fromisoformat(feed_date))
    sched = await _get_schedule_row(db, row["species"], day)
    amount = sched["feed_amount"] if sched else 0
    new_satiety = sched["satiety_end"] if sched else row["current_satiety"]

    async with db.cursor() as cur:
        await cur.execute(
            "REPLACE INTO feed_logs (animal_id, feed_date, amount) VALUES (%s, %s, %s)",
            (animal_id, feed_date, amount)
        )
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE animals SET current_satiety = %s WHERE id = %s",
            (new_satiety, animal_id)
        )
    await db.commit()
    return {"ok": True, "amount": amount, "satiety": new_satiety, "feed_date": feed_date}


@router.delete("/animals/{animal_id}/feed")
async def unfeed_animal(animal_id: int, db: Any = Depends(get_db)):
    today = date.today().isoformat()
    async with db.cursor() as cur:
        await cur.execute("SELECT * FROM animals WHERE id = %s", (animal_id,))
        row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="动物不存在")

    day = _calc_day(row["start_date"])
    sched = await _get_schedule_row(db, row["species"], day)
    prev_satiety = sched["satiety_start"] if sched else row["current_satiety"]

    async with db.cursor() as cur:
        await cur.execute(
            "DELETE FROM feed_logs WHERE animal_id = %s AND feed_date = %s",
            (animal_id, today)
        )
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE animals SET current_satiety = %s WHERE id = %s",
            (prev_satiety, animal_id)
        )
    await db.commit()
    return {"ok": True, "satiety": prev_satiety}


@router.get("/species")
async def list_species(db: Any = Depends(get_db)):
    async with db.cursor() as cur:
        await cur.execute("SELECT `key`, name, emoji FROM species ORDER BY sort_id")
        rows = await cur.fetchall()
    return list(rows)


@router.get("/today/summary")
async def today_summary(db: Any = Depends(get_db)):
    today = date.today()
    async with db.cursor() as cur:
        await cur.execute("SELECT * FROM animals WHERE sold_at IS NULL")
        rows = await cur.fetchall()

    need_feed, has_output = [], []
    for row in rows:
        status = await _build_status(db, row, today)
        if not status.get("is_alive"):
            continue
        if status["feed_needed"] > 0 and not status["fed_today"]:
            need_feed.append(status["nickname"])
        if status["output_today"] > 0:
            has_output.append({"nickname": status["nickname"], "output": status["output_today"]})

    return {
        "today":            today.isoformat(),
        "need_feed_count":  len(need_feed),
        "need_feed_names":  need_feed,
        "has_output":       has_output,
    }
