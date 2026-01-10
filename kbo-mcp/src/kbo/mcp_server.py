from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .service import get_schedule_async
from .realtime_playwright import build_realtime_payload_playwright

# Weather 예제처럼 서버를 직접 실행할 수 있도록 host/port를 지정.
mcp = FastMCP("kbo", host="0.0.0.0", port=8000)
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




def main() -> None:
    # Weather 예제처럼 SSE transport로 서버 실행.
    mcp.run(transport="sse")
    # sse : server-sent events(HTTP 연결을 계속 유지하면서 서버가 이벤트를 스트림으로 보내는 방식)
    # mcp 서버가 클라이언트에 도구 호출 결과/이벤트를 지속적으로 전송하는 통신 방식으로 쓰인다.


if __name__ == "__main__":
    main()
