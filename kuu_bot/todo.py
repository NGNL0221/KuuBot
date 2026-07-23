import json
import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")
DEFAULT_PATH = os.path.join(DATA_DIR, "todos.json")


class TodoModel:
    def __init__(self, path=DEFAULT_PATH):
        self._path = path
        self._items = []
        self._load()

    def _load(self):
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.isfile(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._items = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._items = []

    def _save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._items, f, ensure_ascii=False, indent=2)

    def add(self, text):
        item = {"text": text, "time": time.strftime("%Y-%m-%d %H:%M"), "done": False}
        self._items.append(item)
        self._save()
        return len(self._items) - 1

    def toggle(self, index):
        if 0 <= index < len(self._items):
            self._items[index]["done"] = not self._items[index]["done"]
            self._save()
            return True
        return False

    def remove(self, index):
        if 0 <= index < len(self._items):
            self._items.pop(index)
            self._save()
            return True
        return False

    def update(self, index, text):
        if 0 <= index < len(self._items):
            self._items[index]["text"] = text
            self._save()
            return True
        return False

    def get_all(self):
        return list(self._items)

    def get_pending(self):
        return [t for t in self._items if not t["done"]]

    def format_list(self) -> str:
        items = self._items
        if not items:
            return "暂无待办事项~"
        lines = []
        for i, item in enumerate(items):
            status = "✓" if item["done"] else "○"
            lines.append(f"  {i+1}. [{status}] {item['text']}  ({item['time']})")
        pending = sum(1 for t in items if not t["done"])
        done = sum(1 for t in items if t["done"])
        return f"待办 {len(items)} 条（未完成 {pending} / 已完成 {done}）:\n" + "\n".join(lines)


_todo = None


def get_model(path=DEFAULT_PATH) -> TodoModel:
    global _todo
    if _todo is None:
        _todo = TodoModel(path)
    return _todo
