import re # 정규표현식 사용을 위한 모듈
from datetime import datetime # 수집 시각을 만들기 위해 datetime 클래스를 가져온다 
from urllib.parse import urljoin, urlparse, parse_qs # 게임센터 URL에서 쿼리 파라미터 (gameDate, gameId)를 파싱하는데 사용한다

from playwright.async_api import async_playwright

from .db import GameRow # 크롤링 결과를 담을 데이터 구조
from . import kbo_selectors as sel # CSS 셀렉터들을 sel이라는 이름으로 사용
# CSS 셀릭터는 "웹페이지(HTML)에서 원하는 요소를 찾기 위한 검색 문자열"
# 브라우저 화면에서 어떤 부분을 집어낼지 알려주는 규칙

def _norm(s: str) -> str: # 웹에서 가져온 문자열을 깨끗하게 정리하기 위해 쓰는 함수
    return re.sub(r"\s+", " ", s.strip()) 
    # "/s+" : 여러 개의 공백/탭/줄바꿈을 하나의 공백으로 바꿈
    # strip() : 앞뒤 공백/줄바꿈 제거
    # _는 파이썬 관례로 이 파일이 내부에서만 쓰는 내부(helper) 함수라는 뜻을 담는다.


def _extract_gamecenter_info(href: str) -> tuple[str | None, str | None]:
    """
    예시(네 스샷):
    /Schedule/GameCenter/Main.aspx?gameDate=20250330&gameId=20250330HTHH0&section=REVIEW
    -> gameDate, gameId 추출
    """
    try:
        q = parse_qs(urlparse(href).query) # gameDate=20250330&gameId=20250330HTHH0 이 부분만 뽑고 딕셔너리로 만든다는 의미
        game_date = q.get("gameDate", [None])[0]
        game_id = q.get("gameId", [None])[0]
        return game_date, game_id
    except Exception:
        return None, None


async def scrape_month_schedule(year: int, month: int, series_value: str = "0,9,6") -> list[GameRow]:
    """
    핵심 아이디어:
    - "특정 날짜"를 찾으려면, 그 날짜가 속한 "연/월"로 페이지를 맞춘 뒤
    - 테이블(#tblScheduleList)에서 월 전체를 읽고
    - 나중에 DB에서 날짜로 필터하면 됨.
    """
    mm = f"{month:02d}" # 월을 두 자리 문자열로 변환 (3 -> "03")
    fetched_at = datetime.utcnow().isoformat() # 데이터 수집시간(UTC)을 ISO 문자열로 저장

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) # headless=False는 브라우저가 눈에 보이도록 설정
        page = await browser.new_page()

        await page.goto(sel.SCHEDULE_URL, wait_until="domcontentloaded") # goto(url) : 지정한 url로 이동
        # DOM이 HTML 구조를 다 만든 시점까지 기다리라는 옵션

        # 1) 시리즈(정규/시범/포스트) 선택
        # 정규가 value="0,9,6"로 selected 되어 있음.
        await page.select_option(sel.DDL_SERIES, series_value)
        # select_option : playwright의 페이지 객체에 붙어있는 라이브러리 기능으로, 
        # HTML의 <select> 요소(드롭다운)에서 특정 값을 선택해주는 기능

        # 2) 연/월 선택 ( #ddlYear, #ddlMonth가 존재)
        await page.select_option(sel.DDL_YEAR, str(year))
        await page.select_option(sel.DDL_MONTH, mm)

        # 3) 테이블이 갱신될 시간을 잠깐 줌 (사이트가 JS로 갱신)
        # 더 안정적으로는 특정 행이 로딩될 때까지 wait_for_selector를 써도 됨.
        await page.wait_for_timeout(500)

        # 4) 테이블 행 파싱
        rows = page.locator(sel.TABLE_ROWS) # locator(selector) : 특정 셀렉터에 해당하는 요소 찾기
        n = await rows.count() # locator 메서드로 "현재 선택된 요소가 몇 개 있는지 세어라"의 의미를 가짐

        games: list[GameRow] = [] # 경기 정보를 담을 빈 리스트 준비
        current_day_text = ""  # "09.02(화)" 같은 값이 rowspan 때문에 첫 줄에만 있을 수 있음

        for i in range(n):
            row = rows.nth(i)

            # 날짜 칸 (rowspan으로 첫 행에만 있을 수 있음)
            day_cell = row.locator("td.day") # 행 안에서 날짜칸을 찾는다
            if await day_cell.count():
                current_day_text = _norm(await day_cell.inner_text()) # playwright의 locator메서드로 "해당 요소의 사람이 보이는 텍스트를 가져와라"의 의미를 가짐

            # 시간
            time_text = None
            time_b = row.locator("td.time b")
            if await time_b.count():
                time_text = _norm(await time_b.inner_text())

            # 경기(원정/홈 팀 + 점수 있을 수도)
            play_td = row.locator("td.play")
            if not await play_td.count():
                continue

            spans = play_td.locator("span")
            if await spans.count() < 2:
                continue

            away = _norm(await spans.nth(0).inner_text())
            home = _norm(await spans.nth(-1).inner_text())

            # 점수는 :
            # <em><span class="win">5</span><span>vs</span><span class="lose">3</span></em>
            away_score = home_score = None
            win = play_td.locator("em span.win")
            lose = play_td.locator("em span.lose")
            if await win.count() and await lose.count():
                away_score = int(_norm(await win.first.inner_text()))
                home_score = int(_norm(await lose.first.inner_text()))
            else:
                # 무승부/표기 변화 등으로 win/lose 클래스가 없을 때 숫자만 추출
                score_spans = play_td.locator("em span")
                nums: list[str] = []
                for j in range(await score_spans.count()):
                    text = _norm(await score_spans.nth(j).inner_text())
                    nums.extend(re.findall(r"\d+", text))
                if len(nums) >= 2:
                    away_score = int(nums[0])
                    home_score = int(nums[1])

            # 나머지 컬럼들(구장/TV/라디오/비고)은 td 순서 기반으로 잡는 게 현실적
            tds = row.locator("td")
            td_texts = [_norm(await tds.nth(j).inner_text()) for j in range(await tds.count())]

            # 헤더: 날짜/시간/경기/게임센터/하이라이트/TV/라디오/구장/비고
            # day가 rowspan일 때 행에 day td가 없어서 길이가 달라질 수 있어.
            # 그래서 "뒤에서부터" 구장/비고를 잡는 방식으로 보수적으로 처리.
            stadium = td_texts[-2] if len(td_texts) >= 2 else None
            note = td_texts[-1] if len(td_texts) >= 1 else None

            # TV/라디오도 뒤쪽에서 찾기(구장/비고 바로 앞)
            tv = td_texts[-4] if len(td_texts) >= 4 else None
            radio = td_texts[-3] if len(td_texts) >= 3 else None

            # 게임센터 링크에서 game_id 뽑기(있으면 아주 좋음)
            gamecenter_url = None
            game_id = None
            relay_td = row.locator("td.relay a")
            if await relay_td.count():
                href = await relay_td.first.get_attribute("href") # get_attribute("href") : HTML 속성 값을 가져옴
                if href:
                    gamecenter_url = urljoin(sel.SCHEDULE_URL, href)
                    _, game_id = _extract_gamecenter_info(href)

            # current_day_text는 "09.02(화)"라서 DB에 넣을 "YYYY-MM-DD"로 변환 필요
            # 여기서는 (year, month, day)만 뽑아서 YYYY-MM-DD로 만들자
            m = re.match(r"(\d{2})\.(\d{2})", current_day_text)
            if not m:
                # 날짜 파싱이 안 되면 스킵(구조가 바뀐 경우)
                continue
            dd = int(m.group(2))
            game_date = f"{year}-{month:02d}-{dd:02d}"

            games.append(GameRow(
                game_date=game_date,
                time=time_text,
                away=away,
                home=home,
                away_score=away_score,
                home_score=home_score,
                stadium=stadium or None,
                tv=tv or None,
                radio=radio or None,
                note=note or None,
                game_id=game_id,
                gamecenter_url=gamecenter_url,
                fetched_at=fetched_at,
            ))

        await browser.close()

    return games

# scrape_month_schedule 함수의 로직
# part1 입력/초기값 준비
# part2 브라우저 열고 필터 설정

# part3 테이블 행 읽기
# page.locator("#tblScheduleList tbody tr") → 모든 행
# row.locator("td.day"), td.time, td.play → 각 칸 접근
# inner_text()로 텍스트 추출
# 점수는 span.win/lose 또는 숫자만 뽑아서 처리

# Part 4 GameRow로 정리해서 반환