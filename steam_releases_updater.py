if __name__ == "__main__":
    import asyncio
    from app.core.games import update_release_dates

    asyncio.run(update_release_dates())
