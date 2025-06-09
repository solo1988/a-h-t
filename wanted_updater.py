import requests
import datetime
import time
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import Wanted, Release
from database import SyncSessionLocal

API_KEY = "01dfc51073714f4db8898b2fc7796499"
RAWG_URL = "https://api.rawg.io/api/games"

def fetch_and_store_wanted():
    current_year = datetime.date.today().year
    session: Session = SyncSessionLocal()

    try:
        page = 1
        while True:
            response = requests.get(RAWG_URL, params={
                "platforms": 4,
                "dates": f"{current_year}-01-01,{current_year}-12-31",
                "ordering": "-added",
                "page_size": 40,
                "page": page,
                "key": API_KEY
            })
            data = response.json()
            games = data.get("results", [])
            if not games:
                print("Данные закончились, игр нет на странице", page)
                break

            any_added = False
            for game in games:
                if game["added"] > 0:
                    any_added = True
                    release_date_str = game["released"]
                    if release_date_str:
                        try:
                            release_date = datetime.datetime.strptime(release_date_str, "%Y-%m-%d").date()
                        except ValueError:
                            release_date = None
                    else:
                        release_date = None

                    wanted_game = session.query(Wanted).filter(func.lower(Wanted.name) == game["name"].lower()).first()
                    if wanted_game:
                        updated = False
                        if wanted_game.added != game["added"]:
                            wanted_game.added = game["added"]
                            updated = True
                        if wanted_game.release_date != release_date:
                            wanted_game.release_date = release_date
                            updated = True
                        if updated:
                            print(f"Обновлена игра: {game['name']}, added: {game['added']}")
                    else:
                        wanted = Wanted(
                            name=game["name"],
                            rawg_id=game["id"],
                            added=game["added"],
                            release_date=release_date
                        )
                        session.add(wanted)
                        print(f"Добавлена новая игра: {game['name']}, added: {game['added']}")
                else:
                    continue

            session.commit()

            if not any_added:
                print(f"Достигли конца на странице {page} — все игры с added == 0.")
                break

            print(f"Обработана страница {page}, игр с added > 0: {sum(1 for g in games if g['added'] > 0)}")
            page += 1
            time.sleep(1)

        # Подставляем appid из releases по совпадению имени (без учета регистра)
        wanted_games = session.query(Wanted).filter(Wanted.appid.is_(None)).all()
        for wanted in wanted_games:
            release = session.query(Release).filter(func.lower(Release.name) == wanted.name.lower()).first()
            if release:
                wanted.appid = release.appid

        session.commit()

    finally:
        session.close()


if __name__ == "__main__":
    fetch_and_store_wanted()
