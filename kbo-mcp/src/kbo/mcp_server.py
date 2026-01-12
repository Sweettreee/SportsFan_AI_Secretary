from __future__ import annotations

import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from .service import get_schedule_async
from .places import build_candidates_from_prompt
from .realtime_playwright import build_realtime_payload_playwright

# Weather 예제처럼 서버를 직접 실행할 수 있도록 host/port를 지정.
mcp = FastMCP("kbo", host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
# host="0.0.0.0" 는 모든 네트워크 인터페이스에서 접속을 허용한다는 뜻
# 127.0.0.1은 로컬에서만 접근 가능

@mcp.tool()
async def kbo_schedule(date: str) -> list[dict]:
    """
    Return KBO schedule for a date (YYYY-MM-DD).

    MCP는 함수 시그니처/설명으로 입력 스키마를 만들기 때문에
    파라미터를 명확히 두고 문장을 간결히 유지한다.
    """
    # 로컬 DB 파일을 사용해 데이터 저장 위치를 명확히 한다.
    return await get_schedule_async(db_path="kbo.sqlite", date_yyyy_mm_dd=date)


@mcp.tool()
async def baseball_game_notifier(
    date: str,
    team: str | None = None,
    game_id: str | None = None,
) -> dict:
    """
    Playwright-based real-time info (DOM visible data only).
    """
    return await build_realtime_payload_playwright(
        date_yyyy_mm_dd=date,
        team=team,
        game_id=game_id,
    )


@mcp.tool()
async def realtime_baseball_analyst(
    date: str,
    team: str | None = None,
    game_id: str | None = None,
) -> dict:
    """
    Analysis inputs: facts + derived metrics (from Playwright DOM).
    """
    payload = await build_realtime_payload_playwright(
        date_yyyy_mm_dd=date,
        team=team,
        game_id=game_id,
    )
    return {
        **payload,
        "analysis_instructions": {
            "facts": "Use facts as ground truth; do not invent.",
            "derived_metrics": "Explain deterministic metrics clearly.",
            "model_opinion": "Provide reasoned opinion tied to facts/metrics.",
        },
    }


@mcp.tool()
async def get_restaurant_candidates(prompt: str) -> dict:
    """
    Return restaurant candidates by parsing a natural-language prompt.
    """
    try:
        candidates, stadium_name = await build_candidates_from_prompt(prompt)
        return {
            "candidates": candidates,
            "error": None,
            "stadium_name": stadium_name,
            "output_instructions": (
                "{\n"
                "  \"response_policy\": {\n"
                "    \"must_use_server_json_only\": true,\n"
                "    \"allow_extra_inference\": false,\n"
                "    \"allow_extra_text\": true,\n"
                "    \"must_include_item_format\": true,\n"
                "    \"allow_stadium_guess\": false,\n"
                "    \"must_use_stadium_name\": true,\n"
                "    \"must_follow_output_template\": true,\n"
                "    \"if_candidates_empty\": \"recommendation_unavailable\"\n"
                "  },\n"
                "  \"output_template\": {\n"
                "    \"title\": \"✅ 추천 맛집 리스트 (기본 10곳) - {stadium_name} 기준\",\n"
                "    \"extra_text_rules\": \"템플릿 블록 외 설명은 허용하되, 후보 데이터에서 벗어난 새 사실/추론은 금지\",\n"
                "    \"item_format\": [\n"
                "      \"{index}) {name}\",\n"
                "      \"- 카카오맵: {place_url}\",\n"
                "      \"- 위치: {road_address_or_address}\",\n"
                "      \"- 추천 이유: {reason_based_on_user_preferences}\",\n"
                "      \"- 특징: {features}\",\n"
                "      \"- 추천 메뉴: {recommended_menu}\"\n"
                "    ],\n"
                "    \"constraints\": {\n"
                "      \"max_items\": 10,\n"
                "      \"no_json_output\": true\n"
                "    }\n"
                "  }\n"
                "}"
            ),
        }
    except ValueError as exc:
        message = str(exc)
        ask_text = "날짜/팀 또는 경기장명을 알려주세요. 예: 2025-03-28 삼성 경기 맛집 추천, 한화 볼파크 근처 맛집"
        if "날짜가 필요합니다" in message or "팀명이 필요합니다" in message:
            ask_text = message
        return {
            "candidates": [],
            "error": None,
            "stadium_name": None,
            "output_instructions": (
                "{\n"
                "  \"response_policy\": {\n"
                "    \"must_use_server_json_only\": true,\n"
                "    \"allow_extra_inference\": false,\n"
                "    \"allow_extra_text\": true,\n"
                "    \"must_include_item_format\": true,\n"
                "    \"allow_stadium_guess\": false,\n"
                "    \"must_use_stadium_name\": false,\n"
                "    \"must_follow_output_template\": true,\n"
                "    \"if_candidates_empty\": \"ask_for_date_team\"\n"
                "  },\n"
                "  \"output_template\": {\n"
                "    \"title\": \"\",\n"
                "    \"extra_text_rules\": \"템플릿 블록 외 설명은 허용하되, 후보 데이터에서 벗어난 새 사실/추론은 금지\",\n"
                "    \"item_format\": [\n"
                f"      \"{ask_text}\"\n"
                "    ],\n"
                "    \"constraints\": {\n"
                "      \"max_items\": 1,\n"
                "      \"no_json_output\": true\n"
                "    }\n"
                "  }\n"
                "}"
            ),
        }




def main() -> None:
    load_dotenv()
    # Weather 예제처럼 SSE transport로 서버 실행.
    #mcp.run(transport="sse")
    mcp.run(transport="streamable-http")
    # sse : server-sent events(HTTP 연결을 계속 유지하면서 서버가 이벤트를 스트림으로 보내는 방식)
    # mcp 서버가 클라이언트에 도구 호출 결과/이벤트를 지속적으로 전송하는 통신 방식으로 쓰인다.


if __name__ == "__main__":
    main()
