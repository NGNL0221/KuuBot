import json
import os
import hashlib

MAX_HISTORY = 99999
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _openid_slug(openid: str) -> str:
    return hashlib.md5(openid.encode()).hexdigest()[:12]


def _file_path(openid: str, session_name: str = "default") -> str:
    return os.path.join(DATA_DIR, f"{_openid_slug(openid)}_{session_name}.json")


def _meta_path(openid: str) -> str:
    return os.path.join(DATA_DIR, f"{_openid_slug(openid)}_meta.json")


def load(openid: str, session_name: str = "default") -> list:
    _ensure_dir()
    path = _file_path(openid, session_name)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save(openid: str, session_name: str, messages: list):
    _ensure_dir()
    with open(_file_path(openid, session_name), "w", encoding="utf-8") as f:
        json.dump(messages[-MAX_HISTORY:], f, ensure_ascii=False, indent=2)


def append(openid: str, session_name: str, role: str, content: str):
    messages = load(openid, session_name)
    messages.append({"role": role, "content": content})
    save(openid, session_name, messages)
    return messages


def list_sessions(openid: str) -> list:
    _ensure_dir()
    prefix = _openid_slug(openid) + "_"
    sessions = []
    for fname in os.listdir(DATA_DIR):
        if fname.startswith(prefix) and fname.endswith(".json") and "_meta" not in fname:
            name = fname[len(prefix):-5]
            sessions.append(name)
    return sessions or ["default"]


def clear(openid: str, session_name: str = "default"):
    save(openid, session_name, [])


def rename(openid: str, old_name: str, new_name: str) -> bool:
    old_path = _file_path(openid, old_name)
    new_path = _file_path(openid, new_name)
    if not os.path.isfile(old_path):
        return False
    if os.path.isfile(new_path):
        return False
    os.rename(old_path, new_path)
    return True


def delete(openid: str, session_name: str) -> bool:
    if session_name == "default":
        clear(openid, "default")
        return True
    path = _file_path(openid, session_name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def get_meta(openid: str) -> dict:
    path = _meta_path(openid)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_meta(openid: str, data: dict):
    path = _meta_path(openid)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def get_mode(openid: str) -> str:
    return get_meta(openid).get("mode", "build")


def set_mode(openid: str, mode: str):
    data = get_meta(openid)
    data["mode"] = mode
    _save_meta(openid, data)


def get_debug(openid: str) -> bool:
    return get_meta(openid).get("debug", False)


def set_debug(openid: str, debug: bool):
    data = get_meta(openid)
    data["debug"] = debug
    _save_meta(openid, data)


def get_current_session(openid: str) -> str:
    return get_meta(openid).get("current_session", "default")


def set_current_session(openid: str, name: str):
    data = get_meta(openid)
    data["current_session"] = name
    _save_meta(openid, data)


_admin_openid = ""


def set_admin_openid(openid: str):
    global _admin_openid
    _admin_openid = openid


def get_admin_openid() -> str:
    return _admin_openid


def get_reminders() -> list:
    path = os.path.join(DATA_DIR, "reminders.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def add_reminder(fire_at: float, msg: str, rid: str):
    reminders = get_reminders()
    reminders.append({"fire_at": fire_at, "msg": msg, "id": rid})
    with open(os.path.join(DATA_DIR, "reminders.json"), "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False)


def remove_reminder(rid: str):
    reminders = [r for r in get_reminders() if r["id"] != rid]
    with open(os.path.join(DATA_DIR, "reminders.json"), "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False)


def get_cron_state() -> dict:
    path = os.path.join(DATA_DIR, "cron_state.json")
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def set_cron_state(data: dict):
    state = get_cron_state()
    state.update(data)
    with open(os.path.join(DATA_DIR, "cron_state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f)


def get_summary(openid: str, session_name: str = "default") -> str:
    path = _file_path(openid, session_name) + ".summary"
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def set_summary(openid: str, session_name: str, summary: str):
    path = _file_path(openid, session_name) + ".summary"
    with open(path, "w", encoding="utf-8") as f:
        f.write(summary)


def get_last_user_msg() -> float:
    try:
        with open(os.path.join(DATA_DIR, "last_user_msg.txt"), "r") as f:
            return float(f.read().strip())
    except Exception:
        return 0


def set_last_user_msg(ts: float):
    with open(os.path.join(DATA_DIR, "last_user_msg.txt"), "w") as f:
        f.write(str(ts))
