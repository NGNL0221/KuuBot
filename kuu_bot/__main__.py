import os, json, time, signal, re, uuid, datetime, random, threading
from . import session, cron
from .agent import Agent
from .qq_bot import QQBot
from .tray import KuuTray
from . import stickers

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

    agent = Agent(cfg["deepseek_api_key"], persona, cfg.get("tavily_api_key", ""))
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

        session.set_last_user_msg(time.time())

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
                    "/cancel <编号|ID|all> — 取消提醒\n"
                    "/sticker <标签> — 发送表情包\n"
                    "/todo [内容] — 查看/添加待办\n"
                    "/todocheck <编号> — 划掉待办\n"
                    "/todoremove <编号|1,2,3> — 删除待办\n"
                    "/debug — 切换调试模式（去除消息发送间隔）", msg_id)
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
            elif cmd == "/debug":
                cur = session.get_debug(openid)
                session.set_debug(openid, not cur)
                bot.send_message(openid, f"调试模式 {'关闭' if cur else '开启'}（消息不再有发送间隔）", msg_id)
                return
            elif cmd == "/todo":
                from . import todo
                if not arg:
                    bot.send_message(openid, todo.get_model().format_list())
                else:
                    todo.get_model().add(arg)
                    bot.send_message(openid, f"已添加「{arg}」\n{todo.get_model().format_list()}")
                return
            elif cmd == "/todocheck":
                from . import todo
                try:
                    idx = int(arg.strip()) - 1
                    items = todo.get_model().get_all()
                    if idx < 0 or idx >= len(items):
                        bot.send_message(openid, "编号超出范围")
                    else:
                        todo.get_model().toggle(idx)
                        bot.send_message(openid, f"已划掉「{items[idx]['text']}」\n{todo.get_model().format_list()}")
                except ValueError:
                    bot.send_message(openid, "格式: /todocheck <编号>")
                return
            elif cmd == "/todoremove":
                from . import todo
                arg = arg.strip()
                try:
                    indices = sorted([int(x.strip()) - 1 for x in arg.split(",")], reverse=True)
                    model = todo.get_model()
                    removed = []
                    for idx in indices:
                        items = model.get_all()
                        if 0 <= idx < len(items):
                            removed.append(items[idx]["text"])
                            model.remove(idx)
                    if removed:
                        bot.send_message(openid, "已删除: " + ", ".join(f"「{r}」" for r in removed) + "\n" + model.format_list())
                    else:
                        bot.send_message(openid, "没有有效的编号")
                except ValueError:
                    bot.send_message(openid, "格式: /todoremove <编号> 或 /todoremove 1,2,3")
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
            elif cmd == "/sticker":
                tag = arg.strip() if arg else ""
                if tag:
                    path = stickers.search(tag)
                else:
                    path = stickers.random_sticker()
                if path:
                    bot.send_image(openid, path)
                else:
                    bot.send_message(openid, f"没有找到匹配的表情包" + (f" [标签: {tag}]" if tag else ""), msg_id)
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
            sticker_paths = result.get("stickers", [])
            has_real_tool = result.get("has_real_tool", False)
        except Exception as e:
            reply = f"(出错了: {e})"
            sticker_paths = []
            has_real_tool = False

        now_dt = datetime.datetime.now()
        wrong_years = [str(now_dt.year - 1), str(now_dt.year - 2)]
        if any(f"{y}年" in reply for y in wrong_years):
            correction = agent.ask(
                f"你的回复里年份错了。当前真实时间是 {now_dt.strftime('%Y年%m月%d日 %H:%M')}，不是你说的时间。请用真实时间修正你的回复，直接输出修正后的完整回复。\n\n原始回复: {reply[:600]}")
            if correction:
                reply = correction

        buzzwords = {"搜到", "找到", "改好", "已修改", "已创建", "已删除",
                     "写好了", "已写入", "执行了", "运行了", "已完成",
                     "查到了", "读取了", "已复制", "解压了", "压缩了", "下载了"}
        if any(w in reply for w in buzzwords) and not has_real_tool:
            correction = agent.ask(
                f"你刚才回复说你对主人的文件做了操作（包含以下关键词之一），但实际没有调用任何工具。请诚实回答你现在需要做什么来弥补——是调用工具补上操作，还是直接道歉说刚才没有真的执行？只输出你要发给主人的话。\n\n你的回复: {reply[:500]}")
            if correction:
                reply = correction
        session.append(openid, session_name, "assistant", reply)
        if session.get_mode(openid) == "casual":
            def _casual_send(raw_reply, user_text, sess_name):
                try:
                    prompt = f"做两件事:\n1. 把下面的回复按语义拆成独立句子，一行一句，去掉*动作*标记\n2. 如果有值得记住的事实，用 MEM 行列出。不需要判断质量，全列出来。\n\n回复内容:\n{raw_reply[:800]}\n\n对话上文:\n主人: {user_text[:200]}\n\n输出格式（先分行输出句子，再在任何位置输出 MEM）:\n句子1\n句子2\nMEM: 主人喜欢冰美式 | 偏好,饮食\n句子3"
                    raw = agent.ask(prompt)
                    if not raw:
                        bot.send_message(openid, "（小空在想）")
                        return
                    from . import memory
                    mems = []
                    for line in raw.strip().split("\n"):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        if stripped.upper().startswith("MEM:"):
                            mem_text = stripped[4:].strip()
                            parts = mem_text.split("|", 1)
                            content = parts[0].strip()
                            tags = parts[1].strip() if len(parts) > 1 else ""
                            if content:
                                mems.append((content, tags))
                        else:
                            bot.send_message(openid, stripped)
                            if not session.get_debug(openid):
                                time.sleep(random.uniform(2, 6))
                    if mems:
                        deduped = []
                        for c, t in mems:
                            is_dup = False
                            for dc, _ in deduped:
                                if len(set(c) & set(dc)) / max(len(set(c)), 1) > 0.7:
                                    is_dup = True
                                    break
                            if not is_dup:
                                deduped.append((c, t))
                        vp = "请严格判断以下每条是否值得记入永久记忆库。对每条输出 YES 或 NO，一行一条。\n\n"
                        vp += "✅ YES（长期偏好/反复习惯/重要计划/稳定个人信息）:\n"
                        vp += "  主人每天早上喝冰美式 → YES\n  主人计划下个月去日本 → YES\n  主人习惯12点左右睡觉 → YES\n  主人在河南大学读测控 → YES\n  主人喜欢被小空管着 → YES\n\n"
                        vp += "❌ NO（一次性动作/推测/测试/临时/角色反了/称呼）:\n"
                        vp += "  主人说叫我小空 → NO\n  主人刚刚让我改代码 → NO\n  主人今晚12点睡 → NO\n  主人赶小空去睡觉 → NO（反了，是小空催主人）\n  主人让我搜文件 → NO\n\n"
                        vp += "⚠️ 角色: 用户=主人，小空=AI猫娘女仆\n\n事实:\n"
                        for i, (c, _) in enumerate(deduped, 1):
                            vp += f"{i}. {c}\n"
                        vresult = agent.ask(vp)
                        if vresult:
                            vlines = [l.strip().upper() for l in vresult.strip().split("\n")]
                            for i, (c, t) in enumerate(deduped):
                                if i < len(vlines) and vlines[i] == "YES":
                                    memory.remember(c, t, sess_name)
                except:
                    pass
            threading.Thread(target=_casual_send, args=(reply, text, session_name), daemon=True).start()
        else:
            bot.send_message(openid, reply, msg_id)

            def _scribe_normal(user_text, bot_reply, sess_name):
                try:
                    prompt = f"扫描这段对话。如果有值得记住的事实，用 MEM 行列出。不需要判断质量，全列出来。没有就回复 NONE。\n格式: MEM: 事实内容 | 标签1,标签2\n\n主人: {user_text[:300]}\n小空: {bot_reply[:300]}"
                    result = agent.ask(prompt)
                    if result and result.strip().upper() != "NONE":
                        from . import memory
                        mems = []
                        for line in result.strip().split("\n"):
                            stripped = line.strip()
                            if stripped.upper().startswith("MEM:"):
                                mem_text = stripped[4:].strip()
                                parts = mem_text.split("|", 1)
                                content = parts[0].strip()
                                tags = parts[1].strip() if len(parts) > 1 else ""
                                if content:
                                    mems.append((content, tags))
                        if mems:
                            deduped = []
                            for c, t in mems:
                                is_dup = False
                                for dc, _ in deduped:
                                    if len(set(c) & set(dc)) / max(len(set(c)), 1) > 0.7:
                                        is_dup = True
                                        break
                                if not is_dup:
                                    deduped.append((c, t))
                            vp = "请严格判断以下每条是否值得记入永久记忆库。对每条输出 YES 或 NO，一行一条。\n\n"
                            vp += "✅ YES（长期偏好/反复习惯/重要计划/稳定个人信息）:\n"
                            vp += "  主人每天早上喝冰美式 → YES\n  主人计划下个月去日本 → YES\n  主人习惯12点左右睡觉 → YES\n  主人在河南大学读测控 → YES\n  主人喜欢被小空管着 → YES\n\n"
                            vp += "❌ NO（一次性动作/推测/测试/临时/角色反了/称呼）:\n"
                            vp += "  主人说叫我小空 → NO\n  主人刚刚让我改代码 → NO\n  主人今晚12点睡 → NO\n  主人赶小空去睡觉 → NO（反了，是小空催主人）\n  主人让我搜文件 → NO\n\n"
                            vp += "⚠️ 角色: 用户=主人，小空=AI猫娘女仆\n\n事实:\n"
                            for i, (c, _) in enumerate(deduped, 1):
                                vp += f"{i}. {c}\n"
                            vresult = agent.ask(vp)
                            if vresult:
                                vlines = [l.strip().upper() for l in vresult.strip().split("\n")]
                                for i, (c, t) in enumerate(deduped):
                                    if i < len(vlines) and vlines[i] == "YES":
                                        memory.remember(c, t, sess_name)
                except:
                    pass
            threading.Thread(target=_scribe_normal, args=(text, reply, session_name), daemon=True).start()
        if not sticker_paths:
            fallback = stickers.match_from_text(reply)
            if fallback:
                sticker_paths = [fallback]
        if random.random() < 0.5:
            for sp in sticker_paths:
                try:
                    bot.send_image(openid, sp)
                except:
                    pass



    bot = QQBot(cfg["qq_app_id"], cfg["qq_app_secret"], handle_message)
    print(f"[KuuBot] Starting QQ Bot {cfg['qq_app_id']}")
    bot.start()

    def _send_cron(openid, msg):
        try:
            bot.send_message(openid, msg)
        except:
            pass
    cron.start(_send_cron, agent, bot.send_image)

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
