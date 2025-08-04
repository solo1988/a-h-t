import re
import dateparser

from typing import Optional
from datetime import datetime, date
from app.core.config import settings

def parse_release_date(date_str: str):

    date_str = date_str.strip().lower()
    date_str = re.sub(r'\s*г\.?$', '', date_str).strip()
    date_str = date_str.replace('\xa0', ' ')  # <--- добавь это

    # Английские форматы с днем
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.date()
        except ValueError:
            continue

    # Английские форматы только месяц и год
    for fmt in ("%b %Y", "%B %Y"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue

    # Русские форматы с числом
    match = re.match(r'(\d{1,2})\s+([а-яё]+)\.?\s+(\d{4})', date_str)
    if match:
        day, month_name, year = match.groups()
        month_key = month_name.strip()

        month = settings.RUSSIAN_MONTHS.get(month_key)
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                pass

    # Русские форматы без числа (только месяц и год)
    match = re.match(r'([а-яё.]+)\s+(\d{4})', date_str)
    if match:
        month_name, year = match.groups()
        month = settings.RUSSIAN_MONTHS.get(month_name.strip())
        if month:
            return date(int(year), month, 1)

    # Кварталы английские, например Q1 2025
    match = re.match(r'q([1-4])\s+(\d{4})', date_str)
    if match:
        quarter, year = match.groups()
        month = (int(quarter) - 1) * 3 + 1
        return date(int(year), month, 1)

    # Кварталы русские, например 1 квартал 2025
    match = re.match(r'(\d)\s*квартал\s*(\d{4})', date_str)
    if match:
        quarter, year = match.groups()
        month = (int(quarter) - 1) * 3 + 1
        return date(int(year), month, 1)

    # Просто год
    match = re.match(r'(\d{4})', date_str)
    if match:
        year = int(match.group(1))
        return date(year, 1, 1)

    return None

def parse_release_date_fav(date_str: str) -> Optional[date]:
    if not date_str:
        return None

    # Простейшая проверка: есть ли цифра дня и слово месяца
    # Например: "25 июн. 2025", "8 ноября 2025"
    has_day = re.search(r"\b\d{1,2}\b", date_str)
    has_month = re.search(
        r"(янв|фев|мар|апр|мая|июн|июл|авг|сен|окт|ноя|дек|January|February|March|April|May|June|July|August|September|October|November|December)", date_str,
        re.IGNORECASE)

    if not (has_day and has_month):
        return None

    parsed = dateparser.parse(date_str, settings={"PREFER_DAY_OF_MONTH": "first"})
    return parsed.date() if parsed else None