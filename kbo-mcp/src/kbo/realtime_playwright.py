from __future__ import annotations

import asyncio # 비동기 대기
import time # 시간을 재는 함수(time.monotonic)
from dataclasses import dataclass
from datetime import datetime, timezone # 현재시간 + UTC 표기
from typing import Any # 타입힌트용(무슨 값이든 가능)
from urllib.parse import parse_qs, urlparse # URL 쿼리 파싱

from playwright.async_api import async_playwright

from .service import get_schedule_async, _extract_game_id

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {} # key : URL, value : (저장시간, 데이터)
_LAST_CALL: dict[str, float] = {}

_TTL_SECONDS = 20
_MIN_INTERVAL = 1.0


@dataclass(frozen=True)
class FetchResult:
    data: dict[str, Any] | None
    fetched_at: str
    stale: bool
    error: str | None


def _now_iso() -> str: # 현재 UTC 시간을 iso 포멧으로 반환하라
    return datetime.now(timezone.utc).isoformat()


async def _rate_limit(key: str) -> None:
    last = _LAST_CALL.get(key)
    now = time.monotonic()
    if last is not None:
        wait = _MIN_INTERVAL - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
    _LAST_CALL[key] = time.monotonic()


def _select_game( # 경기 목록 중에서 하나를 선택하는 함수
    games: list[dict[str, Any]],
    team: str | None,
    game_id: str | None,
) -> dict[str, Any] | None:
    if game_id:
        for g in games:
            if _extract_game_id(g.get("gamecenter_url")) == game_id:
                return g
        return None
    if team:
        t = team.strip()
        matches = [g for g in games if t in (g.get("away"), g.get("home"))]
        if len(matches) == 1:
            return matches[0]
        return None
    return games[0] if games else None


async def _text(page, selector: str) -> str | None: # 웹페이지에서 특정 CSS 셀렉터의 텍스트를 읽는 함수
    loc = page.locator(selector)
    if await loc.count():
        return (await loc.first.inner_text()).strip() or None
    return None


async def _table_rows(page, selector: str) -> list[list[str]]: # 테이블의 각 행(tr)을 읽어서 "행별 텍스트 리스트"로 변환
    rows = page.locator(selector)
    out: list[list[str]] = []
    for i in range(await rows.count()):
        row = rows.nth(i)
        cells = row.locator("th, td")
        vals: list[str] = []
        for j in range(await cells.count()):
            vals.append((await cells.nth(j).inner_text()).strip())
        if vals:
            out.append(vals)
    return out


def _parse_int(text: str | None) -> int | None: # 문자열에서 숫자만 뽑아 정수로 변환
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _total_from_line(row: list[str]) -> int | None: # 한 행(이닝 점수 행)에서 마지막 합계 숫자를 구함
    nums = [_parse_int(x) for x in row]
    nums = [n for n in nums if n is not None]
    return nums[-1] if nums else None


def _validate_rows(rows: list[list[str]], label: str, errors: list[str]) -> None:
    if not rows:
        errors.append(f"{label}: empty")


async def _scrape_review(gamecenter_url: str) -> FetchResult: 
    # GameCenter 리뷰 화면을 playwright로 열어서
    # 스코어보드/구장/경기시간 등 DOM에 보이는 정보를 읽어오는 함수
    # 실패하면 재시도하고, 그래도 안 되면 에러/캐시 반환.
    url = gamecenter_url
    if "section=" not in url:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}section=REVIEW"

    key = url
    now = time.monotonic()
    if key in _CACHE:
        cached_time, cached_data = _CACHE[key]
        if now - cached_time < _TTL_SECONDS:
            return FetchResult(cached_data, _now_iso(), False, None)

    await _rate_limit("review")
    backoff = 0.5
    last_err: str | None = None
    for _ in range(3):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector("#tblScordboard2", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(800)

                linescore = await _table_rows(page, "#tblScordboard2 tbody tr")
                summary = await _table_rows(page, "#tblScordboard1 tbody tr")
                rheb = await _table_rows(page, "#tblScordboard3 tbody tr")

                data = {
                    "stadium": await _text(page, "#txtStadium"),
                    "crowd": await _text(page, "#txtCrowd"),
                    "start_time": await _text(page, "#txtStartTime"),
                    "end_time": await _text(page, "#txtEndTime"),
                    "run_time": await _text(page, "#txtRunTime"),
                    "linescore": linescore,
                    "summary": summary,
                    "rheb": rheb,
                    "keyplayer_text": await _text(page, ".keyplayer"),
                }

                await browser.close()
                _CACHE[key] = (time.monotonic(), data)
                return FetchResult(data, _now_iso(), False, None)
        except Exception as exc:
            last_err = str(exc)
            await asyncio.sleep(backoff)
            backoff *= 2

    if key in _CACHE:
        _, cached_data = _CACHE[key]
        return FetchResult(cached_data, _now_iso(), True, last_err)
    return FetchResult(None, _now_iso(), True, last_err or "scrape_failed")


def _derive_metrics(linescore: list[list[str]]) -> dict[str, Any]: 
    # **이닝 점수표(linescore)**에서 합계 점수를 뽑아 **득실차(run_diff)**를 계산한다.
    if len(linescore) < 2:
        return {"run_diff": None}
    away_total = _total_from_line(linescore[0])
    home_total = _total_from_line(linescore[1])
    run_diff = None
    if away_total is not None and home_total is not None:
        run_diff = away_total - home_total
    return {"run_diff": run_diff}


async def _scrape_lineup(gamecenter_url: str) -> FetchResult:
    # GameCenter 프리뷰 화면에서 라인업 테이블을 읽어오는 함수
    url = gamecenter_url
    if "section=" not in url:
        join = "&" if "?" in url else "?"
        url = f"{url}{join}section=PREVIEW"

    key = url
    now = time.monotonic()
    if key in _CACHE:
        cached_time, cached_data = _CACHE[key]
        if now - cached_time < _TTL_SECONDS:
            return FetchResult(cached_data, _now_iso(), False, None)

    await _rate_limit("preview")
    backoff = 0.5
    last_err: str | None = None
    for _ in range(3):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                try:
                    await page.wait_for_selector("#tblAwayLineUp", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(800)

                away = await _table_rows(page, "#tblAwayLineUp tbody tr")
                home = await _table_rows(page, "#tblHomeLineUp tbody tr")
                note = await _text(page, "#txtLineUp")

                data = {
                    "note": note,
                    "away": away,
                    "home": home,
                }

                await browser.close()
                _CACHE[key] = (time.monotonic(), data)
                return FetchResult(data, _now_iso(), False, None)
        except Exception as exc:
            last_err = str(exc)
            await asyncio.sleep(backoff)
            backoff *= 2

    if key in _CACHE:
        _, cached_data = _CACHE[key]
        return FetchResult(cached_data, _now_iso(), True, last_err)
    return FetchResult(None, _now_iso(), True, last_err or "scrape_failed")


async def build_realtime_payload_playwright(
    # 전체 실시간 JSON을 만들어 반환하는 핵심 함수
    # Notifier/Analyst가 모두 이 함수를 사용한다
    # 1. SQLite에서 해당 날짜 경기 목록 조회
    # 2. team/game_id로 경기 선택
    # 3. 리뷰/라인업 Playwright 파싱
    # 4. 오류 검증
    # 5. facts + derived_metrics로 최종 JSON 반환
    date_yyyy_mm_dd: str,
    team: str | None,
    game_id: str | None,
) -> dict[str, Any]:
    games = await get_schedule_async(db_path="kbo.sqlite", date_yyyy_mm_dd=date_yyyy_mm_dd)
    game = _select_game(games, team, game_id)
    if not game or not game.get("gamecenter_url"):
        return {
            "query": {"date": date_yyyy_mm_dd, "team": team, "game_id": game_id},
            "fetched_at": _now_iso(),
            "stale": True,
            "errors": ["no_matching_game_or_url"],
            "facts": {},
        }

    errors: list[str] = []
    review = await _scrape_review(game["gamecenter_url"])
    if review.error:
        errors.append(f"review: {review.error}")

    lineup = await _scrape_lineup(game["gamecenter_url"])
    if lineup.error:
        errors.append(f"lineup: {lineup.error}")

    keyplayer_text = None
    if review.data:
        _validate_rows(review.data.get("linescore", []), "linescore", errors)
        _validate_rows(review.data.get("summary", []), "summary", errors)
        _validate_rows(review.data.get("rheb", []), "rheb", errors)
        keyplayer_text = review.data.get("keyplayer_text")
    if lineup.data:
        _validate_rows(lineup.data.get("away", []), "lineup_away", errors)
        _validate_rows(lineup.data.get("home", []), "lineup_home", errors)

    facts = {
        "schedule_game": game,
        "review": review.data,
        "lineup": lineup.data,
        "key_players": {"text": keyplayer_text} if keyplayer_text else None,
        "fetched_at": {
            "review": review.fetched_at,
            "lineup": lineup.fetched_at,
        },
        "stale": {
            "review": review.stale,
            "lineup": lineup.stale,
        },
        "source_urls": {
            "review": game["gamecenter_url"],
            "lineup": game["gamecenter_url"],
        },
    }
    return {
        "query": {"date": date_yyyy_mm_dd, "team": team, "game_id": game_id},
        "fetched_at": _now_iso(),
        "stale": review.stale or lineup.stale,
        "errors": errors,
        "facts": facts,
        "derived_metrics": _derive_metrics(review.data.get("linescore", []) if review.data else []),
    }
