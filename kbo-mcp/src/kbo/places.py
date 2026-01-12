from __future__ import annotations

import os
import re
from typing import Any

import httpx

from .service import get_schedule_async, get_stadium_by_game_id, _extract_game_id

# 하드코딩된 경기장 좌표(경기장 이름을 키로 사용)
STADIUMS: dict[str, dict[str, Any]] = {
    "잠실": {"name": "잠실야구장", "x": 127.07190258073032, "y": 37.51200542239364},
    "고척": {"name": "고척스카이돔", "x": 126.8670884728618, "y": 37.49849151887496},
    "수원": {"name": "수원KT위즈파크", "x": 127.00979007210005 , "y": 37.29957527349038},
    "문학": {"name": "인천SSG랜더스필드", "x": 126.69331083134149, "y": 37.43680055277793}, 
    "대전": {"name": "대전한화생명볼파크", "x": 127.43153485242281, "y": 36.31613469620863},
    "대구": {"name": "대구삼성라이온즈파크", "x": 128.6817212169836, "y": 35.84042069529301},
    "창원": {"name": "창원NC파크", "x": 128.5820635132696 , "y": 35.22240340386296},
    "사직": {"name": "사직야구장", "x": 129.06144986163022, "y": 35.19376684777871},
    "광주": {"name": "광주기아챔피언스필드", "x": 126.8890795839624, "y": 35.16787568995091}
}


def _get_kakao_api_key() -> str:
    api_key = os.getenv("KAKAO_REST_API_KEY")
    if not api_key:
        raise RuntimeError("KAKAO_REST_API_KEY is not set")
    return api_key


def get_stadium_location_by_name(stadium_name: str) -> dict[str, Any]:
    loc = STADIUMS.get(stadium_name)
    if not loc:
        raise ValueError("Unknown stadium name")
    return loc


async def fetch_food_candidates(
    x: float,
    y: float,
    radius: int = 20000,
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    max_candidates = 45
    url = "https://dapi.kakao.com/v2/local/search/category.json"
    headers = {"Authorization": f"KakaoAK {_get_kakao_api_key()}"}

    all_docs: list[dict[str, Any]] = [] # 수집한 후보들을 담을 리스트 초기화
    async with httpx.AsyncClient() as client: # 비동기 HTTP 클라이언트를 컨텍스트(블록) 동안 열어두고, 블록이 끝나면 자동으로 안전하게 닫아주는 문법
        # requests라는 방법도 있지만 동기이다. 비동기를 하기 위해서는 httpx.AsyncClient를 사용
        # as client : 열어둔 클라이언트를 client라는 변수로 쓰껬다
        for page in range(1, max_pages + 1): 
            if len(all_docs) >= max_candidates: # 45개가 넘으면 break
                break
            params = { # HTTP 쿼리 스트링으로 URL 뒤에 붙을 값들
                "category_group_code": "FD6", # 카테고리 : 음식점
                "x": str(x), # 경도
                "y": str(y), # 위도
                "radius": str(radius), # 20km 반경
                "size": "15", # 한페이지에 15개씩
                "page": str(page), # 지금 몇 페이지 요청하는지
                "sort": "distance", # 거리순 정렬
            }
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json() # 서버가 준 JSON 응답을 파이썬 dict로 바꿈

            docs = data.get("documents", []) # JSON에서 "documents"키를 가져오는데, 없으면 빈리스트 []를 씀
            all_docs.extend(docs) # all_docs에 docs를 붙여넣기

            if data.get("meta", {}).get("is_end"): # 실제로 존재하는 결과를 다줬으면 break
                break

    return all_docs[:max_candidates]


async def validate_candidates_by_keyword(
    candidates: list[dict[str, Any]],
    radius: int = 2000, # 중심 좌표 기준 반경(2km), 같은 이름의 다른 지역 가게가 섞이는 걸 줄이기 위함
) -> list[dict[str, Any]]:
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {_get_kakao_api_key()}"}

    async with httpx.AsyncClient() as client:
        validated: list[dict[str, Any]] = []
        for c in candidates:
            name = c.get("place_name") or c.get("name")
            x = c.get("x")
            y = c.get("y")
            if not name or not x or not y:
                continue
            params = {
                "query": name,# 후보 이름으로만 검색
                "x": str(x), # x,y,radius -> (x,y) 좌표 주변 radius 안에서만 검색
                "y": str(y),
                "radius": str(radius),
            }
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if data.get("documents"): # `documents`가 비어있지 않다는 건 : "name"의 장소가 이 좌표 주변 반경(radius)에서 실제로 검색된다
                validated.append(c)
        return validated


def normalize_place(doc: dict[str, Any]) -> dict[str, Any]: # 데이터 정규화
    return {
        "name": doc.get("place_name"), # .get()은 키가 없을 경우에는 default=None을 반환한다 / get("dis",default) 가능
        "address": doc.get("address_name"),
        "road_address": doc.get("road_address_name"),
        "x": doc.get("x"),
        "y": doc.get("y"),
        "distance_m": int(doc["distance"]) if doc.get("distance") else None, # distance가 있으면 정수로 바꾸고, 없으면 None을 반환
        "place_url": doc.get("place_url"),
        "category_name": doc.get("category_name"),
    }


def _sanitize_prompt(prompt: str) -> str:
    # stadium 관련 표현은 무시한다. (LLM이 경기장을 판단하지 않도록 서버에서 제거)
    stadium_words = list(STADIUMS.keys()) + [ # 경기장 지역(고척,대전)과 아래 이름들(스카이돔,라이온즈파크)를 하나의 리스트로 만들기
        "스카이돔",
        "라이온즈파크",
        "볼파크",
        "파크",
        "돔",
        "구장",
        "야구장",
    ]
    sanitized = prompt
    # 괄호 안에 stadium 관련 단어가 있으면 괄호 구간을 통째로 제거, stadium_words과 겹치는 단어가 하나라도 있다면 괄호 구간을 통쨰로 제거
    for w in stadium_words:
        sanitized = re.sub(rf"\([^)]*{re.escape(w)}[^)]*\)", "", sanitized) # (...) 안에 경기장 단어가 있다면 괄호 전체를 삭제
    for w in stadium_words: 
        sanitized = sanitized.replace(w, "") # 괄호에 없거나, 괄호 밖에 남아있는 경기장 단어를 단어만 삭제
    return sanitized


def _extract_date_and_team(prompt: str) -> tuple[str, str]:
    # 프롬프트에서는 날짜/팀만 추출하고, 경기장 판단은 서버가 수행한다.
    prompt = _sanitize_prompt(prompt) # 필요한 데이터만 추출하고, 왜곡된 정보를 제거(e.g. 키움 경기 -> 키움 고척스카이돔)
    m = re.search(r"\d{4}-\d{2}-\d{2}", prompt)
    if not m:
        raise ValueError("날짜가 필요합니다. 예: '2025-03-28 삼성 경기 기준 맛집 추천' (또는 경기장명으로 요청)")
    date = m.group(0) # 정규표현식으로 찾은 실제 문자열 부분을 꺼냄

    team = None
    for t in ["NC", "한화", "KIA", "삼성", "SSG", "LG", "두산", "KT", "롯데", "키움"]:
        if t in prompt:
            team = t
            break
    if not team:
        raise ValueError("팀명이 필요합니다. 예: '2025-03-28 삼성 경기 기준 맛집 추천' (또는 경기장명으로 요청)")
    return date, team


def _contains_stadium_cue(prompt: str) -> bool:
    cue_words = [
        "구장",
        "야구장",
        "돔",
        "파크",
        "볼파크",
        "스카이돔",
        "필드",
    ]
    return any(w in prompt for w in cue_words)


def _extract_stadium_name(prompt: str) -> str | None:
    if not _contains_stadium_cue(prompt):
        return None

    if re.search(r"(대전\s*한화\s*생명\s*볼파크|한화\s*생명\s*볼파크|대전한화생명볼파크)", prompt):
        return "대전"
    if re.search(r"한화\s*볼파크", prompt):
        return "대전"
    if "볼파크" in prompt and ("한화" in prompt or "대전" in prompt):
        return "대전"

    if re.search(r"(고척\s*스카이돔|고척스카이돔|스카이돔)", prompt):
        return "고척"
    if re.search(r"고척.*(돔|구장|야구장)", prompt):
        return "고척"

    if re.search(r"(잠실.*(구장|야구장)|잠실야구장)", prompt):
        return "잠실"

    if re.search(r"(수원\s*kt\s*위즈파크|kt\s*위즈파크|위즈파크)", prompt, re.IGNORECASE):
        return "수원"

    if re.search(r"(대구\s*삼성\s*라이온즈파크|라이온즈파크)", prompt):
        return "대구"

    if re.search(r"(인천\s*ssg\s*랜더스필드|ssg\s*랜더스필드|랜더스필드|문학.*(구장|야구장))", prompt, re.IGNORECASE):
        return "문학"

    if re.search(r"(창원\s*nc\s*파크|nc\s*파크|창원.*(구장|야구장))", prompt, re.IGNORECASE):
        return "창원"

    if re.search(r"(사직.*(구장|야구장)|사직야구장)", prompt):
        return "사직"

    if re.search(r"(광주\s*(기아|kia)\s*챔피언스필드|챔피언스필드)", prompt, re.IGNORECASE):
        return "광주"

    return None


async def build_candidates_from_prompt(prompt: str) -> tuple[list[dict[str, Any]], str]:
    try:
        date, team = _extract_date_and_team(prompt)
    except ValueError:
        stadium_name = _extract_stadium_name(prompt)
        if not stadium_name:
            raise
        loc = get_stadium_location_by_name(stadium_name)
        raw_docs = await fetch_food_candidates(x=loc["x"], y=loc["y"])
        validated = await validate_candidates_by_keyword(raw_docs)
        return [normalize_place(doc) for doc in validated], stadium_name

    games = await get_schedule_async("kbo.sqlite", date)
    # 같은 날짜에 같은 팀 경기가 여러 개면 첫 번째 경기로 선택한다.
    match = next((g for g in games if team in (g.get("away"), g.get("home"))), None)
    if not match:
        raise ValueError("no matching game for the date/team")

    game_id = _extract_game_id(match.get("gamecenter_url")) # game_id는 정밀한 확인용
    if not game_id:
        stadium_name = match.get("stadium")
        if not stadium_name:
            raise ValueError("stadium not found in schedule")
        loc = get_stadium_location_by_name(stadium_name)
        raw_docs = await fetch_food_candidates(x=loc["x"], y=loc["y"])
        validated = await validate_candidates_by_keyword(raw_docs)
        return [normalize_place(doc) for doc in validated], stadium_name

    stadium_name = await get_stadium_by_game_id(
        db_path="kbo.sqlite",
        date_yyyy_mm_dd=date,
        game_id=game_id,
    )
    if not stadium_name:
        raise ValueError("Unknown game_id for the given date")
    loc = get_stadium_location_by_name(stadium_name)
    raw_docs = await fetch_food_candidates(x=loc["x"], y=loc["y"])
    validated = await validate_candidates_by_keyword(raw_docs)
    return [normalize_place(doc) for doc in validated], stadium_name
