# KBO MCP Server

KBO 일정과 경기 실시간 정보를 MCP 도구로 제공하는 서버입니다. 월 단위 일정은 Playwright로 수집해 SQLite에 캐시하고, GameCenter 페이지에서 DOM 기반으로 리뷰/라인업 정보를 읽어옵니다.

## Features
- 월 단위 KBO 일정 수집 및 SQLite 캐시
- MCP 도구 제공: 일정 조회, 실시간 정보, 분석 입력 JSON
- GameCenter 리뷰/라인업 DOM 파싱 + 간단 지표(run diff) 생성

## Tech Stack
- Python 3.14+
- Playwright (headless Chromium)
- SQLite
- MCP FastMCP (SSE transport)

## Project Structure
- `src/kbo/mcp_server.py`: MCP 서버 엔트리포인트
- `src/kbo/service.py`: 일정 조회/캐시 로직
- `src/kbo/scraper.py`: KBO 일정 크롤러
- `src/kbo/realtime_playwright.py`: GameCenter 리뷰/라인업 파서
- `src/kbo/db.py`: SQLite 스키마/쿼리
- `scripts/run_cli.py`: 일정 조회 CLI 테스트

## Setup
```bash
cd kbo-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install
```

## Run MCP Server
```bash
cd kbo-mcp
python -m kbo.mcp_server
```

## Tools
- `kbo_schedule(date: "YYYY-MM-DD") -> list[dict]`
  - 일정 조회 + 월 캐시 자동 갱신
- `baseball_game_notifier(date, team?, game_id?) -> dict`
  - 리뷰/라인업 DOM 기반 실시간 정보
- `realtime_baseball_analyst(date, team?, game_id?) -> dict`
  - facts + derived_metrics + 분석 지침 포함

## CLI Test
```bash
cd kbo-mcp
python scripts/run_cli.py
```

## Notes
- DB 파일은 실행 위치에 `kbo.sqlite`로 생성됩니다.
- GameCenter 구조가 변경되면 `src/kbo/kbo_selectors.py` 및 파싱 로직 조정이 필요합니다.
