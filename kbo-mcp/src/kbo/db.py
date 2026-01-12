import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

# 일정 1건을 표현하는 데이터 구조
@dataclass(frozen=True)
class GameRow:
    game_date: str            # "YYYY-MM-DD"
    time: str | None
    away: str
    home: str
    away_score: int | None
    home_score: int | None
    stadium: str | None
    tv: str | None
    radio: str | None
    note: str | None
    game_id: str | None       # 있으면 고유키로 쓰기 좋음
    gamecenter_url: str | None
    fetched_at: str           # ISO timestamp


def connect(db_path: str) -> sqlite3.Connection: # sqlite3.connect()가 만들어주는 연결 객체의 타입
    conn = sqlite3.connect(db_path) # 여기서 connect는 실제 sqlite3의 실제 라이브러리 함수를 호출한다
    conn.row_factory = sqlite3.Row # row_factory는 sqlite3 모듈이 미리 정의해 둔 설정 변수
    # row_factory : "SELECT 결과를 어떤 형태로 만들어 줄지"를 정합니다
    # sqlite3.Row : sqlite3 모듈이 제공하는 행 타입 클래스로, 이 타입을 넣으면, 결과 행을 딕셔너리처럼 키로 접근 가능한 객체로 만들어줌
    # 연결 객체의 속성이란 : 객체는 내부에 값(속성)을 가지고 있고, conn.row_factory는 그중 하나로 이 속성은 "이 연결로 조회할 때 결과 행을 어떻게 만들지"를 저장합니다.
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """
    - schedules: 경기 일정 저장
    - month_cache: 'YYYY-MM' 단위로 언제 마지막으로 수집했는지(캐시) 저장,다시 크롤링할지 말지 경정하기 위한 "신선도 표시"
    """
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_date TEXT NOT NULL,         -- YYYY-MM-DD
        time TEXT,
        away TEXT NOT NULL,
        home TEXT NOT NULL,
        away_score INTEGER,
        home_score INTEGER,
        stadium TEXT,
        tv TEXT,
        radio TEXT,
        note TEXT,
        game_id TEXT,
        gamecenter_url TEXT,
        fetched_at TEXT NOT NULL
    );
    """)

    # game_id가 있으면 중복 저장 방지에 유리
    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_schedules_unique_game
    ON schedules(game_date, time, away, home, COALESCE(game_id, ''));
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS month_cache (
        year INTEGER NOT NULL,
        month INTEGER NOT NULL,
        series TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        PRIMARY KEY (year, month, series)
    );
    """)

    conn.commit()


def upsert_month_cache(conn: sqlite3.Connection, year: int, month: int, series: str, fetched_at: str) -> None:
    # 없으면 insert하고, 존재하는 필드면 가져온 시간만 업데이트
    conn.execute("""
    INSERT INTO month_cache(year, month, series, fetched_at)
    VALUES(?,?,?,?)
    ON CONFLICT(year, month, series) DO UPDATE SET fetched_at=excluded.fetched_at
    """, (year, month, series, fetched_at))
    conn.commit() # 변경을 확정(commit) 해야 실제로 저장됨,fetched_at : "이 데이터를 언제 수집했는지" 기록한 시간 문자열(ISO형식)


def is_month_cache_fresh(
    conn: sqlite3.Connection,
    year: int,
    month: int,
    series: str,
    ttl_minutes: int = 60 * 12,  # 기본 12시간 캐시
) -> bool:
    """
    캐시가 신선하면(True) -> Playwright로 다시 안 긁고 DB만 사용.
    """
    row = conn.execute("""
    SELECT fetched_at FROM month_cache
    WHERE year=? AND month=? AND series=?
    """, (year, month, series)).fetchone()

    if not row:
        return False

    last = datetime.fromisoformat(row["fetched_at"])
    return datetime.utcnow() - last < timedelta(minutes=ttl_minutes) # True(캐시가 아직 신선하다), False(캐시가 오래됌)


def insert_games(conn: sqlite3.Connection, games: Iterable[GameRow]) -> None: # 여기서 Iterable을 받은 이유는 리스트뿐만 아니라 튜플,제너레이터 등 '나열 가능한 것'이라도 받게 만들기 위해 사용함
    cur = conn.cursor() # conn은 DB에 연결된 선, cursor은 그 선으로 명령을 보내는 도구
    cur.executemany("""
    INSERT OR IGNORE INTO schedules(
        game_date, time, away, home, away_score, home_score,
        stadium, tv, radio, note, game_id, gamecenter_url, fetched_at
    )
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, [ # INSERT OR IGNORE : 새 데이터를 넣거나 이미 같은 데이터가 있으면 그냥 무시하고 넘어간다
        (
            g.game_date, g.time, g.away, g.home, g.away_score, g.home_score,
            g.stadium, g.tv, g.radio, g.note, g.game_id, g.gamecenter_url, g.fetched_at
        )
        for g in games
    ])
    conn.commit()


def get_games_by_date(conn: sqlite3.Connection, date_yyyy_mm_dd: str) -> list[GameRow]:
    rows = conn.execute("""
    SELECT * FROM schedules
    WHERE game_date=?
    ORDER BY time, away, home
    """, (date_yyyy_mm_dd,)).fetchall() 
    # ? 자리에 값을 넣을 때 튜플로 전달해야되서 (date_yyyy_mm_dd,) 형태의 쉼표가 1개짜리 튜플을 만든거야
    # .fetchall() 은 SQL 실행 결과의 모든 행을 리스트로 가져오는 메소드

    out: list[GameRow] = [] # list[GameRow]가 타입힌트인 변수 out을 만들어라
    for r in rows:
        out.append(GameRow( # 여기는 리스트 컴프리헨션이 아니라 빈 리스트를 만들고, for문으로 append하는 방식
            game_date=r["game_date"],
            time=r["time"],
            away=r["away"],
            home=r["home"],
            away_score=r["away_score"],
            home_score=r["home_score"],
            stadium=r["stadium"],
            tv=r["tv"],
            radio=r["radio"],
            note=r["note"],
            game_id=r["game_id"],
            gamecenter_url=r["gamecenter_url"],
            fetched_at=r["fetched_at"],
        ))
    return out


def get_stadium_by_game_id(
    conn: sqlite3.Connection,
    date_yyyy_mm_dd: str,
    game_id: str,
) -> str | None:
    row = conn.execute("""
    SELECT stadium FROM schedules
    WHERE game_date=? AND game_id=?
    LIMIT 1
    """, (date_yyyy_mm_dd, game_id)).fetchone()
    return row["stadium"] if row else None
