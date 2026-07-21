import time
import random
import datetime
import threading
import requests
from . import session
from . import stickers


MORNING_RANGE = (6, 40, 7, 0)
SLEEP_HOUR = 22
SLEEP_MIN = 55
SLEEP_INTERVAL_MIN = 600
SLEEP_INTERVAL_MAX = 1200

MORNING_MSGS = [
    "主人早安~ *揉揉眼睛* 已经 {t} 了，该起床啦！",
    "新的一天开始了喵！*猫耳朵竖起来* 主人快起来~ 已经 {t} 了！",
    "太阳晒到尾巴了呀主人！*轻轻推了推主人* 都 {t} 啦！",
]

SLEEP_MSGS = [
    "主人还不睡吗？*担心地晃了晃猫尾巴* 已经 {t} 了呢...",
    "太晚了主人~ *小声嘟囔* 再不睡明天该没精神了... 已经 {t} 了",
    "主人~ 猫猫困了，主人也该休息啦 *揉眼睛* 都 {t} 了",
]

_send_func = None
_send_image_func = None
_agent = None
_running = False
_sleep_disabled = False


def start(send_message, agent=None, send_image=None):
    global _send_func, _agent, _running, _send_image_func
    _send_func = send_message
    _agent = agent
    _send_image_func = send_image
    _running = True
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


def stop():
    global _running
    _running = False


def disable_sleep():
    global _sleep_disabled
    _sleep_disabled = True


def enable_sleep():
    global _sleep_disabled
    _sleep_disabled = False


def _loop():
    global _sleep_disabled
    today_morning_done = ""
    while _running:
        now = datetime.datetime.now()
        today = now.strftime("%Y%m%d")
        openid = session.get_admin_openid()
        h, m = now.hour, now.minute
        ts = now.strftime("%H:%M")

        # ── Morning ──
        if (h == MORNING_RANGE[0] and m >= MORNING_RANGE[1]) or (h == MORNING_RANGE[2] and m < MORNING_RANGE[3]):
            if today_morning_done != today:
                today_morning_done = today
                state = session.get_cron_state()
                if state.get("morning_done") != today:
                    delay = random.randint(0, 20 * 60)
                    time.sleep(delay)
                    now2 = datetime.datetime.now()
                    if _running and MORNING_RANGE[0] <= now2.hour <= MORNING_RANGE[2]:
                        ts2 = now2.strftime("%H:%M")
                        session.set_cron_state({"morning_done": today})
                        if openid and _send_func and _agent:
                            try:
                                mode = session.get_meta(openid).get("mode", "build")
                                casual_note = ""
                                if mode == "casual":
                                    casual_note = "（强制：真人闲聊模式。禁止动作描写，简短不加句号，偶尔错别字）"
                                result = _agent.ask(casual_note + f"用猫娘语气喊主人起床，已经{ts2}了，简短一两句话")
                                msg = result or random.choice(MORNING_MSGS).format(t=ts2)
                                _send_func(openid, msg)
                                session_name = session.get_current_session(openid)
                                session.append(openid, session_name, "assistant", msg)
                            except:
                                pass

        # ── Sleep reminder ──
        elif h >= SLEEP_HOUR and m >= SLEEP_MIN and not _sleep_disabled:
            _do_sleep_remind(openid, ts, today)

        # ── Reminders ──
        _check_reminders(openid, now)

        # ── Random chat (9:00-22:00, every 30-60 min, not during sleep) ──
        if 9 <= h < 22 and not _sleep_disabled:
            _random_chat(openid, today)

        # ── Reset sleep at 4am ──
        if h == 4 and m < 5:
            _sleep_disabled = False

        time.sleep(30)


def _do_sleep_remind(openid, ts, today):
    state = session.get_cron_state()
    key = f"sleep_last_{today}"
    last = state.get(key, 0)
    if time.time() - last > random.randint(SLEEP_INTERVAL_MIN, SLEEP_INTERVAL_MAX):
        session.set_cron_state({key: time.time()})
        if openid and _send_func and _agent:
            try:
                mode = session.get_meta(openid).get("mode", "build")
                casual_note = ""
                if mode == "casual":
                    casual_note = "（强制：真人闲聊模式。禁止动作描写，简短不加句号，偶尔错别字）"
                result = _agent.ask(casual_note + f"用猫娘语气提醒主人该睡觉了，已经{ts}了，简短一两句话")
                msg = result or random.choice(SLEEP_MSGS).format(t=ts)
                _send_func(openid, msg)
                session_name = session.get_current_session(openid)
                session.append(openid, session_name, "assistant", msg)
            except:
                pass


def _check_reminders(openid, now):
    fired = []
    for r in session.get_reminders():
        if now.timestamp() >= r["fire_at"]:
            if openid and _send_func and _running:
                _send_func(openid, r["msg"])
            fired.append(r["id"])
    for rid in fired:
        session.remove_reminder(rid)


def _random_chat(openid, today):
    if not _agent or not openid:
        return
    state = session.get_cron_state()
    key = f"chat_last_{today}"
    last = state.get(key, 0)
    interval = random.randint(1800, 3600)
    if time.time() - last < interval:
        return
    session.set_cron_state({key: time.time()})

    # 50% chance: no topic, just casual chat
    if random.random() < 0.5:
        topic_hint = ""
    else:
        topics = _fetch_topics()
        if topics:
            used = set(state.get("used_topics", []))
            topic_hint = f"\n当前热门话题（优先选ACGN相关的，避开已用: {', '.join(list(used)[-3:])}）:\n{topics}"
            # Track used topics
            new_used = list(used)
            for line in topics.split("\n"):
                new_used.append(line)
            if len(new_used) > 50:
                new_used = new_used[-20:]
            session.set_cron_state({"used_topics": new_used})
        else:
            topic_hint = ""
    try:
        mode = session.get_meta(openid).get("mode", "build")
        casual_note = ""
        if mode == "casual":
            casual_note = "（强制：真人闲聊模式。禁止动作描写，简短一两句，不加句号，偶尔错别字）"
        now = datetime.datetime.now()
        wd = ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()]
        h = now.hour
        if h < 6:
            ctx = "凌晨，主人可能在熬夜"
        elif h < 9:
            ctx = "早上，主人刚醒或在吃早饭"
        elif h < 12:
            ctx = "上午，主人可能在上班上课"
        elif h < 14:
            ctx = "中午，刚吃完饭"
        elif h < 18:
            ctx = "下午"
        elif h < 22:
            ctx = "晚上，放松时间"
        else:
            ctx = "深夜，主人该睡了"
        time_ctx = f"现在是{wd} {now.strftime('%H:%M')}，{ctx}。"
        result = _agent.chat([{
            "role": "user",
            "content": casual_note + f"（系统主动搭话。{time_ctx}根据时间场景随意聊一两句，禁止直接说'今天是星期几'。可以是吐槽、卖萌、小段子）" + topic_hint
        }])
        msg = result.get("reply", "").strip()
        if msg and _send_func and _running:
            _send_func(openid, msg)
            # 20% chance: add a matching sticker
            if random.random() < 0.2 and _send_image_func:
                sticker = stickers.match_from_text(msg)
                if not sticker:
                    sticker = stickers.random_sticker()
                if sticker:
                    try:
                        ok, _ = _send_image_func(openid, sticker)
                    except:
                        pass
            try:
                session_name = session.get_current_session(openid)
                session.append(openid, session_name, "assistant", msg)
            except:
                pass
    except:
        pass


def _fetch_topics():
    try:
        h = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get("https://api.bilibili.com/x/web-interface/popular?ps=10", headers=h, timeout=10)
        data = resp.json()
        lines = []
        for item in data.get("data", {}).get("list", [])[:10]:
            title = item.get("title", "")
            tag = item.get("tname", "")
            lines.append(f"[{tag}] {title}")
        return "\n".join(lines)
    except:
        return ""
