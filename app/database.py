import aiosqlite
import os

DB_PATH = os.environ.get("DB_PATH", "/app/data/farm.db")

# 旧版英文 key → 新版中文 key 的迁移映射
_KEY_MIGRATION = {
    "panda":      "熊猫",
    "salamander": "娃娃鱼",
    "crocodile":  "鳄鱼",
    "leopard":    "豹子",
    "macaw":      "金刚鹦鹉",
}


async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _create_tables(db)
        await _migrate(db)
        await _seed(db)


# ── 建表 ──────────────────────────────────────────────────────────────────────

async def _create_tables(db: aiosqlite.Connection):
    """三张核心表：饲养计划基表（species + feeding_schedule）、养育动物表、喂养记录表"""

    # ① 饲养计划基表 - 物种维度
    await db.execute("""
        CREATE TABLE IF NOT EXISTS species (
            key             TEXT    PRIMARY KEY,                              -- 物种标识（中文名，如"熊猫"），同时作为外键引用
            name            TEXT    NOT NULL,                                 -- 物种显示名称
            emoji           TEXT    NOT NULL DEFAULT '🐾',                   -- 物种 emoji 图标
            initial_satiety INTEGER NOT NULL,                                 -- 养殖第1天的初始饱食度
            decay_per_2days INTEGER NOT NULL,                                 -- 每2天自然衰减的饱食度点数
            juvenile_days   INTEGER NOT NULL,                                 -- 幼年期天数
            adult_days      INTEGER NOT NULL,                                 -- 成年期天数
            max_extra_days  INTEGER NOT NULL,                                 -- 可通过游玩/拜访额外延长的最大寿命天数
            total_days      INTEGER NOT NULL                                  -- 完整养殖周期总天数（含额外寿命）
        )
    """)

    # ② 饲养计划基表 - 每日计划维度
    await db.execute("""
        CREATE TABLE IF NOT EXISTS feeding_schedule (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            species_key   TEXT    NOT NULL REFERENCES species(key) ON DELETE CASCADE, -- 所属物种
            day           INTEGER NOT NULL,                                            -- 养殖第几天（从1开始）
            stage         TEXT    NOT NULL,                                            -- 所处阶段（幼年期/成年期/额外寿命）
            satiety_start INTEGER NOT NULL,                                            -- 当天开始时的饱食度（喂养前）
            feed_amount   INTEGER NOT NULL DEFAULT 0,                                  -- 当天建议喂养的饲料数量（0表示无需喂）
            satiety_end   INTEGER NOT NULL,                                            -- 当天结束时的饱食度（喂养后）
            output        INTEGER NOT NULL DEFAULT 0,                                  -- 当天产出数量（0表示无产出）
            UNIQUE(species_key, day)
        )
    """)

    # ③ 养育动物表
    await db.execute("""
        CREATE TABLE IF NOT EXISTS animals (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname         TEXT    NOT NULL,                                          -- 动物昵称
            species          TEXT    NOT NULL REFERENCES species(key),                 -- 物种（关联 species.key）
            start_date       TEXT    NOT NULL,                                          -- 养殖开始日期（第1天），格式 YYYY-MM-DD
            extra_days       INTEGER NOT NULL DEFAULT 0,                               -- 已获得的额外寿命天数（0~max_extra_days）
            current_satiety  INTEGER DEFAULT NULL,                                     -- 当前饱食度（喂养后实时更新）
            sold_at          TEXT    DEFAULT NULL,                                      -- 售出时间（NULL 表示未售出，逻辑删除标记）
            created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))   -- 记录创建时间
        )
    """)

    # ④ 喂养记录表
    await db.execute("""
        CREATE TABLE IF NOT EXISTS feed_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            animal_id   INTEGER NOT NULL REFERENCES animals(id) ON DELETE CASCADE, -- 关联动物
            feed_date   TEXT    NOT NULL,                                            -- 喂养日期，格式 YYYY-MM-DD
            amount      INTEGER NOT NULL,                                            -- 实际喂养饲料数量
            UNIQUE(animal_id, feed_date)                                             -- 每只动物每天只记录一次
        )
    """)

    await db.commit()


# ── 迁移 ──────────────────────────────────────────────────────────────────────

async def _migrate(db: aiosqlite.Connection):
    """兼容旧版数据库升级"""
    async with db.execute("PRAGMA table_info(animals)") as cur:
        cols = {row["name"] for row in await cur.fetchall()}

    # 旧版缺少的列
    if "sold_at" not in cols:
        await db.execute("ALTER TABLE animals ADD COLUMN sold_at TEXT DEFAULT NULL")
    if "current_satiety" not in cols:
        await db.execute("ALTER TABLE animals ADD COLUMN current_satiety INTEGER DEFAULT NULL")

    # 英文 key → 中文 key 迁移
    async with db.execute("SELECT key FROM species LIMIT 1") as cur:
        first = await cur.fetchone()

    if first and first["key"] in _KEY_MIGRATION:
        # 更新 animals 表中的 species 列
        for old, new in _KEY_MIGRATION.items():
            await db.execute(
                "UPDATE animals SET species = ? WHERE species = ?", (new, old)
            )
        # 清空旧物种数据（_seed 会重新写入中文 key）
        await db.execute("DELETE FROM feeding_schedule")
        await db.execute("DELETE FROM species")

    # 补全 current_satiety（旧动物记录）
    await db.execute("""
        UPDATE animals SET current_satiety = (
            SELECT fs.satiety_start FROM feeding_schedule fs
            WHERE fs.species_key = animals.species AND fs.day = 1
        )
        WHERE current_satiety IS NULL
    """)

    await db.commit()


# ── Seed ──────────────────────────────────────────────────────────────────────

async def _seed(db: aiosqlite.Connection):
    """饲养计划基表为空时，从 牧场饲养攻略.md 解析并写入"""
    async with db.execute("SELECT COUNT(*) AS cnt FROM species") as cur:
        if (await cur.fetchone())["cnt"] > 0:
            return

    from .seed_parser import parse_feeding_guide
    species_list = parse_feeding_guide()

    for cfg in species_list:
        await db.execute(
            """
            INSERT OR IGNORE INTO species
              (key, name, emoji, initial_satiety, decay_per_2days,
               juvenile_days, adult_days, max_extra_days, total_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cfg["key"], cfg["name"], cfg["emoji"],
                cfg["initial_satiety"], cfg["decay_per_2days"],
                cfg["juvenile_days"], cfg["adult_days"],
                cfg["max_extra_days"], cfg["total_days"],
            ),
        )
        for day, info in cfg["schedule"].items():
            await db.execute(
                """
                INSERT OR IGNORE INTO feeding_schedule
                  (species_key, day, stage, satiety_start, feed_amount, satiety_end, output)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cfg["key"], day, info["stage"],
                    info["satiety_start"], info["feed"],
                    info["satiety_end"], info["output"],
                ),
            )

    await db.commit()
