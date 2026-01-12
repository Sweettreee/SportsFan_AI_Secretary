import asyncio
import re

from dotenv import load_dotenv

from kbo.places import build_candidates_from_prompt


async def main() -> None:
    load_dotenv()
    prompt = "2025-04-01 NC 경기 기준으로 근처 맛집 후보 뽑아줘. 매운 음식 좋아하고, 술집은 빼줘."

    m = re.search(r"\d{4}-\d{2}-\d{2}", prompt)
    if not m:
        raise RuntimeError("date not found in prompt")
    date = m.group(0)

    team = None
    for t in ["NC", "한화", "KIA", "삼성", "SSG", "LG", "두산", "KT", "롯데", "키움"]:
        if t in prompt:
            team = t
            break
    if not team:
        raise RuntimeError("team not found in prompt")

    candidates, stadium_name = await build_candidates_from_prompt(prompt)
    print(f"stadium_name={stadium_name}")
    print(f"count={len(candidates)}")
    for c in candidates:
        print(c)


if __name__ == "__main__":
    asyncio.run(main())
