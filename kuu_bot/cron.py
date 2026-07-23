import time
import random
import datetime
import threading
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

        # ── Memory maintenance ──
        _memory_maintenance(today)

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

    last_user_msg = session.get_last_user_msg()
    if last_user_msg == 0:
        return

    elapsed = time.time() - last_user_msg
    if elapsed < 1800:
        return

    state = session.get_cron_state()
    key = f"chat_after_user"
    last_chat = state.get(key, 0)
    if last_chat >= last_user_msg:
        return

    if elapsed < random.randint(1800, 3600):
        return

    session.set_cron_state({key: time.time()})

    session_name = session.get_current_session(openid)
    history = session.load(openid, session_name)[-6:]
    ctx_str = ""
    if history:
        lines = []
        for m in history:
            role = "主人" if m["role"] == "user" else "小空"
            lines.append(f"[{role}]: {m['content'][:200]}")
        ctx_str = "\n\n📋 最近对话:\n" + "\n".join(lines)

    try:
        from . import todo
        pending = todo.get_model().get_pending()
        if pending:
            todo_ctn = "\n".join(f"  · {t['text']}" for t in pending[:5])
            ctx_str += f"\n\n📝 主人当前待办（未完成）:\n{todo_ctn}"
    except:
        pass

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
        elapsed_min = int(elapsed // 60)
        result = _agent.chat([{
            "role": "user",
            "content": casual_note + f"（系统主动搭话。{time_ctx}距离上次对话已过{elapsed_min}分钟。根据最近对话上下文，继续未完成话题、衍生相关话题、或开启全新话题。简短一两句，禁止直接说'星期几'或'现在是几点'）" + ctx_str
        }])
        msg = result.get("reply", "").strip()
        if msg and _send_func and _running:
            _send_func(openid, msg)
            if random.random() < 0.2 and _send_image_func:
                sticker = stickers.match_from_text(msg)
                if not sticker:
                    sticker = stickers.random_sticker()
                if sticker:
                    try:
                        _send_image_func(openid, sticker)
                    except:
                        pass
            try:
                session.append(openid, session_name, "assistant", msg)
            except:
                pass
    except:
        pass


def _memory_maintenance(today: str):
    state = session.get_cron_state()
    key = f"mem_maint_{today}"
    last = state.get(key, 0)
    if time.time() - last < 300:
        return
    session.set_cron_state({key: time.time()})
    try:
        from . import memory
        memory.run_lifecycle()
    except:
        pass

    if _agent:
        last_user = session.get_last_user_msg()
        if last_user > 0 and time.time() - last_user >= 3600:
            deep_key = f"mem_deep"
            last_deep = state.get(deep_key, 0)
            if time.time() - last_deep >= 7200:
                try:
                    from . import memory
                    frags = memory.get_unconsolidated_fragments()
                    if len(frags) >= 2:
                        _agent._deep_consolidate()
                        session.set_cron_state({deep_key: time.time()})
                except:
                    pass
