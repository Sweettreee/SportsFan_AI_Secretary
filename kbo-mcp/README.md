# KBO MCP Server

KBO 일정/실시간 정보를 MCP 도구로 제공하는 서버입니다. 월 단위 일정은 Playwright로 수집해 SQLite에 캐시하고, GameCenter 페이지에서 DOM 기반 리뷰/라인업 정보를 읽어옵니다. 맛집 추천은 Kakao Local API로 후보를 수집하고, 키워드 재검색으로 실제 검색 가능한 후보만 유지합니다.

## Features
- 월 단위 KBO 일정 수집 및 SQLite 캐시
- MCP 도구 제공: 일정 조회, 실시간 정보, 분석 입력 JSON
- GameCenter 리뷰/라인업 DOM 파싱 + 간단 지표(run diff) 생성
- Kakao Local REST API로 경기장 주변 맛집 후보 수집 (최대 45)
- Kakao 키워드 재검색으로 “실제 검색 가능” 후보만 유지

## Tech Stack
- Python 3.14+
- Playwright (headless Chromium)
- SQLite
- MCP FastMCP (SSE transport)
- Kakao Local REST API

## Project Structure
- `src/kbo/mcp_server.py`: MCP 서버 엔트리포인트
- `src/kbo/service.py`: 일정 조회/캐시 로직
- `src/kbo/scraper.py`: KBO 일정 크롤러
- `src/kbo/realtime_playwright.py`: GameCenter 리뷰/라인업 파서
- `src/kbo/db.py`: SQLite 스키마/쿼리
- `src/kbo/places.py`: Kakao 장소 검색 + 정규화 + 후보 수집
- `scripts/run_cli.py`: 일정 조회 CLI 테스트
- `scripts/test_candidates.py`: 맛집 후보 수집 테스트

## Setup
```bash
cd kbo-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install
```

## Environment
- `.env`는 `python-dotenv`로 자동 로드됩니다.
- `KAKAO_REST_API_KEY`가 필요합니다 (맛집 후보 수집 도구 사용 시).
- 예시: `kbo-mcp/.env`

## Run MCP Server
```bash
cd kbo-mcp
python -m kbo.mcp_server
```
uv 사용 시:
```bash
cd kbo-mcp
PYTHONPATH=src uv run python -m kbo.mcp_server
```

## Tools
- `kbo_schedule(date: "YYYY-MM-DD") -> list[dict]`
  - 일정 조회 + 월 캐시 자동 갱신 (기본 12시간 TTL)
- `baseball_game_notifier(date, team?, game_id?) -> dict`
  - 리뷰/라인업 DOM 기반 실시간 정보 (캐시 20초, 호출 간 1초 rate-limit)
- `realtime_baseball_analyst(date, team?, game_id?) -> dict`
  - facts + derived_metrics + 분석 지침 포함
- `get_restaurant_candidates(prompt) -> dict`
  - 자연어 프롬프트에서 날짜/팀만 추출 후 서버가 경기장 판단
  - 경기장명 단서가 있으면 날짜/팀 없이도 경기장 기반 후보 수집
  - 반환 형식: `{"candidates": [...], "error": None, "stadium_name": str | None, "output_instructions": str}`
  - 후보는 최대 45개까지, 적으면 있는 만큼 반환
  - `output_instructions`로 최종 응답 템플릿과 “후보만 사용” 규칙 제공
  - 날짜/팀/경기장 정보가 부족하면 안내 템플릿을 반환

## LLM Output Format (User-Friendly)
최종 추천 응답은 아래 JSON 지침을 따라야 하며, 실제 출력은 JSON이 아닌 템플릿 형식으로 제공합니다.

```json
{
  "response_policy": {
    "must_use_server_json_only": true,
    "allow_extra_inference": false,
    "allow_extra_text": true,
    "must_include_item_format": true,
    "allow_stadium_guess": false,
    "must_use_stadium_name": true,
    "must_follow_output_template": true,
    "if_candidates_empty": "recommendation_unavailable"
  },
  "output_template": {
    "title": "✅ 추천 맛집 리스트 (기본 10곳) - {stadium_name} 기준",
    "extra_text_rules": "템플릿 블록 외 설명은 허용하되, 후보 데이터에서 벗어난 새 사실/추론은 금지",
    "item_format": [
      "{index}) {name}",
      "- 카카오맵: {place_url}",
      "- 위치: {road_address_or_address}",
      "- 추천 이유: {reason_based_on_user_preferences}",
      "- 특징: {features}",
      "- 추천 메뉴: {recommended_menu}"
    ],
    "constraints": {
      "max_items": 10,
      "no_json_output": true
    }
  }
}
```

## CLI Test
```bash
cd kbo-mcp
python scripts/run_cli.py
```

## Candidates Test
```bash
cd kbo-mcp
PYTHONPATH=src python scripts/test_candidates.py
```

## Notes
- DB 파일은 실행 위치에 `kbo.sqlite`로 생성됩니다.
- GameCenter 구조가 변경되면 `src/kbo/kbo_selectors.py` 및 파싱 로직 조정이 필요합니다.
- 프롬프트에서 stadium 단서는 제거한 뒤 일정 기반으로 경기장을 결정합니다. 단, 날짜/팀이 없고 경기장명이 명시되면 경기장 기반으로 후보 수집을 시도합니다.
- MCP 서버는 기본적으로 `0.0.0.0:8000`에서 SSE transport로 실행됩니다.
