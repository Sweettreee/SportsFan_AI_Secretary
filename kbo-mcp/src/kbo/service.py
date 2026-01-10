from datetime import datetime

from .db import ( # .은 현재 패키지 내부를 뜻하는 상대 import이다. 외부패키지/모듈과 이름충돌이 나지 않게 하기 위함이다
    connect, init_db, insert_games, get_games_by_date,
    is_month_cache_fresh, upsert_month_cache
)
from .scraper import scrape_month_schedule


async def ensure_month_cached_async(
    db_path: str,
    year: int,
    month: int,
    series: str = "0,9,6",
) -> None:
    """
    async 환경에서 asyncio.run 대신 await로 수집한다.
    """
    conn = connect(db_path)  # conn : SQLite 연결 객체(connection) ; DB와의 통로라서 여러 쿼리를 실행하려면 이 객체가 필요함
    init_db(conn) # "테이블이 없으면 만들고, 있으면 그대로 두는" 방식  -> 기존 데이터를 지우지 않는다

    if is_month_cache_fresh(conn, year, month, series):
        return

    games = await scrape_month_schedule(year, month, series)
    insert_games(conn, games)

    upsert_month_cache(conn, year, month, series, datetime.utcnow().isoformat())
    conn.close()


async def get_schedule_async(db_path: str, date_yyyy_mm_dd: str) -> list[dict]:
    """
    async MCP tool에서 사용하는 비동기 버전.
    """
    year, month, _ = map(int, date_yyyy_mm_dd.split("-")) # split을 통해 list가 만들어짐 "2025-03-30" -> ["2025","03","30"]
    await ensure_month_cached_async(db_path, year, month)

    conn = connect(db_path) # SQLite에 있는 파일에 연결함 , conn은 DB에 접근할 수 있는 손잡이
    rows = get_games_by_date(conn, date_yyyy_mm_dd) # 
    conn.close() # DB 연결 닫기

    return [ # 리스트 컴프리헨션 ; ['rows'에서 하나 꺼냄 -> dict생성 -> 리스트에 추가 -> 반복] => 곧바로 반환됌
        {
            "date": r.game_date,
            "time": r.time,
            "away": r.away,
            "home": r.home,
            "score": None if (r.away_score is None or r.home_score is None) else f"{r.away_score}-{r.home_score}",
            "stadium": r.stadium,
            "tv": r.tv,
            "radio": r.radio,
            "note": r.note,
            "gamecenter_url": r.gamecenter_url,
        }
        for r in rows
    ]
