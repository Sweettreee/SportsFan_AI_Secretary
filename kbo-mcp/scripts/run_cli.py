import json
import asyncio
from kbo.service import get_schedule_async

if __name__ == "__main__":
    db_path = "kbo.sqlite"
    date = "2025-08-02"  # 테스트 날짜
    result = asyncio.run(get_schedule_async(db_path, date))
    print(json.dumps(result, ensure_ascii=False, indent=2))
