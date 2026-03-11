import os
import aiomysql

_pool: aiomysql.Pool | None = None


async def get_db():
    async with _pool.acquire() as conn:
        yield conn


async def init_db():
    global _pool
    _pool = await aiomysql.create_pool(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        db=os.environ.get("DB_NAME", "farm"),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=aiomysql.DictCursor,
    )
    async with _pool.acquire() as conn:
        await _create_tables(conn)
        await _seed(conn)


# ── 建表 ──────────────────────────────────────────────────────────────────────

async def _create_tables(conn: aiomysql.Connection):
    async with conn.cursor() as cur:
        # ① 饲养计划基表 - 物种维度
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS species (
                sort_id         INT          NOT NULL AUTO_INCREMENT UNIQUE,
                `key`           VARCHAR(100) NOT NULL PRIMARY KEY,
                name            VARCHAR(100) NOT NULL,
                emoji           VARCHAR(10)  NOT NULL DEFAULT '🐾',
                initial_satiety INT          NOT NULL,
                decay_per_2days INT          NOT NULL,
                juvenile_days   INT          NOT NULL,
                adult_days      INT          NOT NULL,
                max_extra_days  INT          NOT NULL,
                total_days      INT          NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # ② 饲养计划基表 - 每日计划维度
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS feeding_schedule (
                id            INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
                species_key   VARCHAR(100) NOT NULL,
                day           INT          NOT NULL,
                stage         VARCHAR(50)  NOT NULL,
                satiety_start INT          NOT NULL,
                feed_amount   INT          NOT NULL DEFAULT 0,
                satiety_end   INT          NOT NULL,
                output        INT          NOT NULL DEFAULT 0,
                UNIQUE KEY uq_species_day (species_key, day),
                FOREIGN KEY (species_key) REFERENCES species(`key`) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # ③ 养育动物表
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS animals (
                id               INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
                nickname         VARCHAR(100) NOT NULL,
                species          VARCHAR(100) NOT NULL,
                start_date       VARCHAR(10)  NOT NULL,
                extra_days       INT          NOT NULL DEFAULT 0,
                current_satiety  INT          DEFAULT NULL,
                sold_at          VARCHAR(20)  DEFAULT NULL,
                created_at       DATETIME     NOT NULL DEFAULT NOW()
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # ④ 喂养记录表
        await cur.execute("""
            CREATE TABLE IF NOT EXISTS feed_logs (
                id          INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
                animal_id   INT          NOT NULL,
                feed_date   VARCHAR(10)  NOT NULL,
                amount      INT          NOT NULL,
                UNIQUE KEY uq_animal_date (animal_id, feed_date),
                FOREIGN KEY (animal_id) REFERENCES animals(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

    await conn.commit()


# ── Seed ──────────────────────────────────────────────────────────────────────

async def _seed(conn: aiomysql.Connection):
    """饲养计划基表为空时，从 牧场饲养攻略.md 解析并写入"""
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) AS cnt FROM species")
        row = await cur.fetchone()
        if row["cnt"] > 0:
            return

    from .seed_parser import parse_feeding_guide
    species_list = parse_feeding_guide()

    async with conn.cursor() as cur:
        for cfg in species_list:
            await cur.execute(
                """
                INSERT IGNORE INTO species
                  (`key`, name, emoji, initial_satiety, decay_per_2days,
                   juvenile_days, adult_days, max_extra_days, total_days)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    cfg["key"], cfg["name"], cfg["emoji"],
                    cfg["initial_satiety"], cfg["decay_per_2days"],
                    cfg["juvenile_days"], cfg["adult_days"],
                    cfg["max_extra_days"], cfg["total_days"],
                ),
            )
            for day, info in cfg["schedule"].items():
                await cur.execute(
                    """
                    INSERT IGNORE INTO feeding_schedule
                      (species_key, day, stage, satiety_start, feed_amount, satiety_end, output)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        cfg["key"], day, info["stage"],
                        info["satiety_start"], info["feed"],
                        info["satiety_end"], info["output"],
                    ),
                )

    await conn.commit()
