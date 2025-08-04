import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if __name__ == "__main__":
    import asyncio
    from app.core.games import check_daily_releases

    asyncio.run(check_daily_releases())
