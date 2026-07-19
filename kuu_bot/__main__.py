import os, json, time, signal, re, uuid, datetime, random
from . import session, cron
from .agent import Agent
from .qq_bot import QQBot
from .tray import KuuTray

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

REMIND_RE = re.compile(r"(\d+)\s*(分钟|小时|秒)\s*后?")
CLOCK_RE = re.compile(r"(明天)?\s*(下午|晚上|中午|早上|上午|凌晨)?\s*(\d{1,2})\s*[点:：](\d{1,2})?\s*[分]?")


def _to_24h(h: int, period: str) -> int:
    if period in ("下午", "晚上"):
        if h != 12:
            h += 12
    elif period in ("凌晨",):
        return h
    elif period in ("中午",):
        return 12 if h == 12 else h
    return h


def _parse_reminder(text: str) -> tuple:
    """Return (message, delay_seconds)."""
    cm = CLOCK_RE.search(text)
    if cm:
        h = int(cm.group(3))
        m = int(cm.group(4) or 0)
        period = cm.group(2) or ""
        tomorrow = cm.group(1)

        if not period:
            if datetime.datetime.now().hour >= 12:
                h += 12 if h != 12 else 0

        h = _to_24h(h, period)
        if tomorrow:
            h += 24

        now = datetime.datetime.now()
        target = now.replace(hour=h % 24, minute=m, second=0, microsecond=0)
        target += datetime.timedelta(days=h // 24)

        if target <= now:
            target += datetime.timedelta(days=1)

        delay = int((target - now).total_seconds())
        msg = CLOCK_RE.sub("", text).strip()
        if not msg:
            msg = f"主人你设的提醒到啦~ *猫耳朵抖了抖*"
        return msg, max(60, delay)

    m = REMIND_RE.search(text)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if unit == "小时":
            delay = num * 3600
        elif unit == "秒":
            delay = num
        else:
            delay = num * 60
        msg = REMIND_RE.sub("", text).strip()
        if not msg:
            msg = f"主人你设的提醒到啦~ *猫耳朵抖了抖*"
        return msg, delay
    else:
        return text.strip() or "主人你设的提醒到啦~", 3600


def main():
    config_path = os.path.join(CONFIG_DIR, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    persona_path = os.path.join(CONFIG_DIR, "persona.txt")
    persona = ""
    if os.path.isfile(persona_path):
        with open(persona_path, "r", encoding="utf-8") as f:
            persona = f.read()

    agent = Agent(cfg["deepseek_api_key"], persona)
    admin_openid = cfg.get("admin_openid", "")
    if admin_openid:
        session.set_admin_openid(admin_openid)
    running = True

    def on_exit():
        nonlocal running
        running = False

    tray = KuuTray(on_exit)
    tray.start()
    print("[KuuBot] Tray icon ready")

    signal.signal(signal.SIGINT, lambda *a: on_exit())
    signal.signal(signal.SIGTERM, lambda *a: on_exit())

    def handle_message(openid: str, content: str, msg_id: str):
        text = content.strip()
        if not text:
            return

        if not admin_openid:
            bot.send_message(openid,
                f"设置模式 — 你的 OpenID:\n{openid}\n\n"
                "请填入 config.json 的 admin_openid 字段后重启 Bot", msg_id)
            return

        if openid != admin_openid:
            bot.send_message(openid, "此 Bot 为私人使用，暂不接受陌生人消息")
            return

        # Sleep keyword detection
        sleep_words = ["晚安", "睡了", "困了", "休息", "去睡", "睡觉", "安", "好梦"]
        if any(w in text for w in sleep_words):
            cron.disable_sleep()
        wake_words = ["早安", "早啊", "醒了", "起来了", "起床"]
        if any(w in text for w in wake_words):
            cron.enable_sleep()

        session_name = session.get_current_session(openid)
        current = session.load(openid, session_name)

        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "/help":
                bot.send_message(openid, "/help — 显示指令列表\n"
                    "/casual — 真人闲聊模式\n"
                    "/formal — 恢复正常模式\n"
                    "/new — 创建新会话\n"
                    "/list — 列出所有会话\n"
                    "/switch <名称> — 切换会话\n"
                    "/rename <新名称> — 重命名\n"
                    "/delete <编号|名称|all> — 删除\n"
                    "/remind <时间> <内容> — 设置提醒\n"
                    "/reminders — 查看提醒\n"
                    "/cancel <编号|ID|all> — 取消提醒", msg_id)
                return
            if cmd == "/new":
                new_name = arg if arg else datetime.datetime.now().strftime("%m%d-%H%M")
                session.set_current_session(openid, new_name)
                session.save(openid, new_name, [])
                bot.send_message(openid, f"新会话 [{new_name}] 已创建~ 旧会话保留在 /list 里", msg_id)
                return
            elif cmd == "/list":
                names = session.list_sessions(openid)
                lines = ["所有会话:"] + [f"  {i+1}. {n}" for i, n in enumerate(names)]
                lines.append("发送 /delete <编号> 删除，或 /delete all 删除全部")
                bot.send_message(openid, "\n".join(lines), msg_id)
                return
            elif cmd == "/casual":
                session.set_mode(openid, "casual")
                bot.send_message(openid, "好滴（切了闲聊模式", msg_id)
                return
            elif cmd == "/formal":
                session.set_mode(openid, "build")
                bot.send_message(openid, "已恢复正常模式", msg_id)
                return
            elif cmd == "/switch":
                if not arg:
                    bot.send_message(openid, "用法: /switch 会话名", msg_id)
                    return
                session_name = arg
                session.set_current_session(openid, session_name)
                current = session.load(openid, session_name)
                bot.send_message(openid, f"已切换到 [{session_name}]", msg_id)
            elif cmd == "/rename":
                if not arg:
                    bot.send_message(openid, "用法: /rename 新名称", msg_id)
                    return
                old_name = session.get_current_session(openid)
                if old_name == arg:
                    bot.send_message(openid, "新旧名称相同", msg_id)
                    return
                if session.rename(openid, old_name, arg):
                    session.set_current_session(openid, arg)
                    bot.send_message(openid, f"会话已重命名: [{old_name}] → [{arg}]", msg_id)
                else:
                    bot.send_message(openid, "重命名失败，检查名称是否已存在", msg_id)
                return
            elif cmd == "/delete":
                if not arg:
                    bot.send_message(openid, "用法: /delete <编号> 或 /delete <名称> 或 /delete all", msg_id)
                    return
                if arg.lower() == "all":
                    names = session.list_sessions(openid)
                    count = len(names)
                    for n in names:
                        session.delete(openid, n)
                    session.save(openid, "default", [])
                    session.set_current_session(openid, "default")
                    bot.send_message(openid, f"已删除全部 {count} 个会话，已创建新的默认会话", msg_id)
                    return
                if arg.isdigit():
                    names = session.list_sessions(openid)
                    idx = int(arg) - 1
                    if 0 <= idx < len(names):
                        arg = names[idx]
                    else:
                        bot.send_message(openid, "编号超出范围，用 /list 查看", msg_id)
                        return
                if session.delete(openid, arg):
                    if session.get_current_session(openid) == arg:
                        remaining = session.list_sessions(openid)
                        if remaining:
                            next_s = remaining[0]
                            session.set_current_session(openid, next_s)
                            msg = f"会话 [{arg}] 已删除，已切换到 [{next_s}]"
                        else:
                            session.save(openid, "default", [])
                            session.set_current_session(openid, "default")
                            msg = "所有会话已清空，已创建新的默认会话"
                    else:
                        msg = f"会话 [{arg}] 已删除"
                    bot.send_message(openid, msg, msg_id)
                else:
                    bot.send_message(openid, "删除失败，检查名称是否正确", msg_id)
                return
            elif cmd == "/remind":
                if not arg:
                    bot.send_message(openid, "用法: /remind 30分钟后提醒我喝水", msg_id)
                    return
                remind_msg, delay_sec = _parse_reminder(arg)
                rewrite = agent.ask(f"请用自然的猫娘女仆语气改写这句话，直接输出: 「{remind_msg}」")
                if rewrite:
                    remind_msg = rewrite
                fire_at = time.time() + delay_sec
                rid = uuid.uuid4().hex[:8]
                session.add_reminder(fire_at, remind_msg, rid)
                bot.send_message(openid, f"已设提醒~ {int(delay_sec//60)}分钟后小空会提醒你哦！", msg_id)
                return
            elif cmd == "/reminders":
                reminders = session.get_reminders()
                if not reminders:
                    bot.send_message(openid, "当前没有待提醒", msg_id)
                    return
                lines = []
                for i, r in enumerate(reminders):
                    remain = int(r["fire_at"] - time.time())
                    if remain > 3600:
                        ts = f"{remain//3600}小时{(remain%3600)//60}分钟"
                    elif remain > 60:
                        ts = f"{remain//60}分钟"
                    else:
                        ts = f"{remain}秒"
                    lines.append(f"{i+1}. {r['id']} — {ts}后: {r['msg'][:40]}")
                lines.append("/cancel <编号> 取消")
                bot.send_message(openid, "\n".join(lines), msg_id)
                return
            elif cmd == "/cancel":
                if not arg:
                    bot.send_message(openid, "用法: /cancel <编号> 或 /cancel all", msg_id)
                    return
                if arg.lower() == "all":
                    reminders = session.get_reminders()
                    for r in reminders:
                        session.remove_reminder(r["id"])
                    bot.send_message(openid, f"已取消全部 {len(reminders)} 个提醒", msg_id)
                    return
                reminders = session.get_reminders()
                if arg.isdigit():
                    idx = int(arg) - 1
                    if 0 <= idx < len(reminders):
                        arg = reminders[idx]["id"]
                    else:
                        bot.send_message(openid, "编号超出范围，用 /reminders 查看", msg_id)
                        return
                matched = [r for r in reminders if r["id"].startswith(arg)]
                if not matched:
                    bot.send_message(openid, f"未找到 ID 以 [{arg}] 开头的提醒", msg_id)
                elif len(matched) > 1:
                    ids = " / ".join(r["id"] for r in matched)
                    bot.send_message(openid, f"多个匹配: {ids}，请更精确指定", msg_id)
                else:
                    session.remove_reminder(matched[0]["id"])
                    bot.send_message(openid, f"已取消提醒 [{matched[0]['id']}]", msg_id)
                return
            else:
                bot.send_message(openid, "可用: /new /list /switch /rename /delete /delete all /remind /reminders /cancel", msg_id)
                return

        current = session.append(openid, session_name, "user", text)
        try:
            result = agent.chat(current, openid, session_name)
            reply = result.get("reply", "(小空说不出话...)")
        except Exception as e:
            reply = f"(出错了: {e})"
        session.append(openid, session_name, "assistant", reply)
        if session.get_mode(openid) == "casual":
            reply = re.sub(r'\*[^*]+\*', '', reply).strip()
            reply = re.sub(r'\n\s*\n', '\n', reply)
            sentences = re.split(r'[。！？\n]+', reply)
            sentences = [s.strip() for s in sentences if s.strip()][:random.randint(1, 5)]
            for sent in sentences:
                bot.send_message(openid, sent)
                time.sleep(random.uniform(2, 10))
        else:
            bot.send_message(openid, reply, msg_id)

    bot = QQBot(cfg["qq_app_id"], cfg["qq_app_secret"], handle_message)
    print(f"[KuuBot] Starting QQ Bot {cfg['qq_app_id']}")
    bot.start()

    def _send_cron(openid, msg):
        try:
            bot.send_message(openid, msg)
        except:
            pass
    cron.start(_send_cron, agent)

    while running:
        # Process Windows messages for tray
        import ctypes
        class MSG(ctypes.Structure):
            _fields_=[('hwnd',ctypes.wintypes.HWND),('message',ctypes.c_uint),
                      ('wParam',ctypes.wintypes.WPARAM),('lParam',ctypes.wintypes.LPARAM),
                      ('time',ctypes.c_uint32),
                      ('pt',type('P',(ctypes.Structure,),{'_fields_':[('x',ctypes.c_long),('y',ctypes.c_long)]}))]
        msg=MSG()
        while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg),None,0,0,1):
            if msg.message==0x0012:running=False;break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.1)

    bot.stop()
    cron.stop()
    tray.stop()
    print("[KuuBot] Stopped")


if __name__ == "__main__":
    main()
