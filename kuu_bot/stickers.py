import json
import os
import random

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(CONFIG_DIR, "stickers.json")
STICKER_DIR = os.path.join(CONFIG_DIR, "stickers")


def _load():
    if os.path.isfile(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("stickers", [])
    return []


def search(tag: str) -> str | None:
    """Return a random sticker path matching the tag."""
    items = _load()
    matches = [s for s in items if tag in s.get("tags", [])]
    if matches:
        s = random.choice(matches)
        path = os.path.join(STICKER_DIR, s["file"])
        if os.path.isfile(path):
            return path
    return None


def search_by_keywords(keywords: list) -> str | None:
    """Search by multiple keywords, return first match."""
    items = _load()
    for kw in keywords:
        matches = [s for s in items if kw in s.get("tags", [])]
        if matches:
            s = random.choice(matches)
            path = os.path.join(STICKER_DIR, s["file"])
            if os.path.isfile(path):
                return path
    return None


def random_sticker() -> str | None:
    """Return any random sticker path."""
    items = _load()
    if items:
        s = random.choice(items)
        path = os.path.join(STICKER_DIR, s["file"])
        if os.path.isfile(path):
            return path
    return None


def match_from_text(text: str) -> str | None:
    """Match sticker from text content using tag overlap."""
    items = _load()
    matches = []
    for s in items:
        for tag in s.get("tags", []):
            if tag in text:
                path = os.path.join(STICKER_DIR, s["file"])
                if os.path.isfile(path):
                    matches.append(path)
                    break
    if matches:
        return random.choice(matches)
    return None
