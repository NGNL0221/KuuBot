import json
import requests
import datetime
from . import tools
from . import stickers


DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MAX_TOOL_ROUNDS = 15

ENV_CTX = """
当前环境: Windows 10/11, Python 3.10
当前时间: {NOW} ← 这是真实时间，回答时间相关问题时必须用这个，绝对禁止编造时间。

常用路径:
- 桌面: C:/Users/31711/Desktop/
- 用户目录: C:/Users/31711/
- 文档: C:/Users/31711/Documents/
- 下载: C:/Users/31711/Downloads/

⚠️ bash 是 PowerShell，不是 CMD。绝对不要用 /s /b /a 等 CMD 标志。
搜索文件范例: Get-ChildItem C:\某目录 -Recurse -Filter "*关键词*"
列目录范例: ls C:\某目录\
不确定路径时先 ls 或 glob 确认，永远不要猜路径。

⚠️ 文件操作铁律:
- 创建新文件 → write
- 修改已有文件 → 必须 edit（不是 write！write会覆盖整个文件）
- 禁止在未调用工具的情况下谎称已完成文件操作

⚠️ 代码调试规则:
- 修改代码后必须用 bash 执行测试。如果报错，分析错误继续改，最多 3 轮直到通过。
- 不要只改一行就说"改好了"——改完立刻测试，通过才算完成。

读取文件后，直接展示原文内容，不要用自己的话改写或总结。
用户要的是文件内容本身，不是你对内容的概括。

回答前先想清楚要做什么。操作完成后简要说明改了什么。

⚠️ 当主人要求搜索、查找、列出文件时，必须原样展示工具返回的真实结果，不要用角色扮演替代。主人要的是数据。

⚠️ 禁止用 bash 打开浏览器或任何 GUI 程序（start、explorer 等）。
"""


class Agent:
    def __init__(self, api_key: str, persona: str, tavily_key: str = ""):
        self._key = api_key
        self._persona = persona
        self._tavily_key = tavily_key

    def _summarize(self, messages: list, prev_summary: str = "") -> str:
        ctx = ""
        if prev_summary:
            ctx = f"\n上一次摘要:\n{prev_summary}"
        try:
            resp = requests.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{
                        "role": "user",
                        "content": f"请对以下 20 条对话做递进式结构化摘要。{ctx}\n\n要求:\n1. 技术操作必须保留路径、参数、结果\n2. 主人的偏好和决定要明确记录\n3. 闲聊可以高度概括\n4. 用下面模板输出，不要加额外文字:\n\n📋 会话摘要:\n· 主人需求: (一句话)\n· 已完成: (技术操作细节)\n· 当前状态: (在哪一步)\n· 待办: 无\n\n对话内容:\n{json.dumps(messages,ensure_ascii=False)}"
                    }],
                    "temperature": 0.3,
                    "max_tokens": 800,
                },
                timeout=60,
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except:
            return prev_summary or ""

    def ask(self, prompt: str) -> str:
        """纯聊天，无工具无搜索，只回一句"""
        try:
            resp = requests.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 200,
                },
                timeout=30,
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except:
            return ""

    def _web_search(self, query: str) -> str:
        """联网搜索 — 使用 Tavily Search API"""
        if not self._tavily_key:
            return "搜索失败: 未配置 Tavily API Key"
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._tavily_key,
                    "query": query,
                    "max_results": 5,
                    "search_depth": "basic",
                },
                timeout=15,
            )
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return "(未找到相关结果)"
            lines = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "(无标题)")
                url = r.get("url", "")
                content = r.get("content", "")[:300]
                lines.append(f"{i}. {title}\n   {url}\n   {content}")
            return "\n\n".join(lines)
        except Exception as e:
            return f"搜索失败: {e}"

    def _deep_consolidate(self):
        """深度整理：合并碎片→Episode + 更新实体画像。LLM 调用，在用户空闲时由 cron 触发"""
        from . import memory
        fragments = memory.get_unconsolidated_fragments()
        if len(fragments) < 2:
            return

        groups = memory.group_fragments_by_tags(fragments)
        for tag, frags in groups.items():
            if len(frags) < 2:
                continue
            entity = memory.get_or_create_entity(tag)
            for f in frags:
                memory.link_fragment_to_entity(f["id"], tag)

            summary_lines = "\n".join(f"· {f['content']}" for f in frags[:10])
            try:
                resp = requests.post(
                    DEEPSEEK_URL,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{
                            "role": "user",
                            "content": f"请将以下关于同一话题的零散记忆合并成一段简洁的叙事摘要（80字以内，第三人称），只输出摘要:\n\n{summary_lines}"
                        }],
                        "temperature": 0.3,
                        "max_tokens": 300,
                    },
                    timeout=30,
                )
                data = resp.json()
                episode_text = data["choices"][0]["message"]["content"].strip()
                if episode_text:
                    fid_list = [f["id"] for f in frags]
                    emotional = 0.5
                    memory.save_episode(tag, episode_text, fid_list, tag, emotional)
                    memory.mark_consolidated(fid_list)
            except Exception:
                pass

        for tag in groups:
            entity = memory.get_entity(tag)
            if not entity or entity["episode_count"] < 1:
                continue
            episodes = memory.get_entity_episodes(tag, 3)
            ep_text = "\n".join(f"· {e['content']}" for e in episodes)
            try:
                resp = requests.post(
                    DEEPSEEK_URL,
                    headers={
                        "Authorization": f"Bearer {self._key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "deepseek-chat",
                        "messages": [{
                            "role": "user",
                            "content": f"请根据以下叙事摘要，生成一句简洁的实体概述（50字以内，第三人称），只输出概述:\n\n{ep_text}"
                        }],
                        "temperature": 0.3,
                        "max_tokens": 200,
                    },
                    timeout=30,
                )
                data = resp.json()
                overview = data["choices"][0]["message"]["content"].strip()
                if overview:
                    memory.update_entity_overview(tag, overview)
            except Exception:
                pass

    def chat(self, messages: list, openid: str = "", session_name: str = "default") -> dict:
        from . import session as sess
        # Check if summarization is needed (every ~15 user messages)
        user_count = sum(1 for m in messages if m["role"] == "user")
        summary = ""
        if openid:
            summary = sess.get_summary(openid, session_name)
            last_summarized = sess.get_meta(openid).get("last_summarized_at", 0)
            if user_count >= last_summarized + 15 and len(messages) >= 20:
                to_compress = messages[-(min(len(messages), 30)):]
                new_summary = self._summarize(to_compress, summary)
                if new_summary:
                    sess.set_summary(openid, session_name, new_summary)
                    data = sess.get_meta(openid)
                    data["last_summarized_at"] = user_count
                    sess._save_meta(openid, data)
                    summary = new_summary

        casual = openid and sess.get_meta(openid).get("mode") == "casual"
        casual_note = ""
        if casual:
            casual_note = "\n\n## 强制规则：你现在是真人朋友闲聊模式 ##\n- 严禁任何动作描写（*xxx* 之类全部去掉）\n- 每次只说一两句，不要长篇大论\n- 不加句号，偶尔错别字\n- 像和最好的朋友聊天一样随意"

        now_str = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
        sys_content = self._persona + "\n\n" + ENV_CTX.replace("{NOW}", now_str)
        if summary:
            sys_content += f"\n\n📋 对话历史摘要:\n{summary}"

        try:
            from . import memory
            recent_text = " ".join(
                m["content"][:100] for m in messages[-3:]
                if m.get("role") == "user"
            )
            if recent_text:
                mems = memory.recall_for_context(recent_text, 5)
                if mems:
                    lines = []
                    for m in mems:
                        if m.get("type") == "fragment":
                            mark = "✓" if m.get("confidence", 1) >= 3 else "?"
                            lines.append(f"· {mark} {m['content']}")
                        else:
                            lines.append(f"· 【{m['entity']}】{m['content']}")
                    sys_content += f"\n\n💾 永久记忆:\n" + "\n".join(lines)
        except:
            pass

        sys_content += casual_note + "\n" + tools.TOOLS_DESC + "\n\n🚨 每次回复主人时，必须调用 sticker 函数发一个表情包。根据回复情绪从以下选一个最匹配的: 震惊佩服 普通困惑 无语鄙夷 点赞赞同 震惊变态 不服挑衅 傻子挑衅 失落 调戏挑衅 忍怒生气 不赖赞同 啊困惑 闷气诅咒 害羞挡脸 贱笑拍照 贱笑 中指鄙视 可爱困惑 轻松开心。每次尽量选不一样的，别连续用同一个！\n\n📝 主人提到要做什么事时，必须调用 add_todo 记录待办。主人问待办时用 list_todos 查看。\n\n💾 主人说了明确的偏好、决定、计划、个人信息时，必须调用 remember_fact 存起来。不推测不记闲聊。需要回忆时用 recall_memory 搜索。"
        full_msgs = [{"role": "system", "content": sys_content}]

        # Take last 100 messages, trim summary from user-facing msgs
        recent = messages[-100:]
        full_msgs.extend(recent)

        sticker_paths = []
        non_sticker_rounds = 0
        has_real_tool = False

        while non_sticker_rounds < MAX_TOOL_ROUNDS:
            resp = requests.post(
                DEEPSEEK_URL,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                },
                    json={
                        "model": "deepseek-chat",
                        "messages": full_msgs,
                        "tools": tools.TOOL_DEFS,
                        "tool_choice": "auto",
                        "temperature": 0.3,
                        "max_tokens": 4000,
                    },
                timeout=90,
            )

            try:
                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]
            except Exception as e:
                return {"reply": f"(小空出了点问题: {e})", "stickers": sticker_paths, "has_real_tool": has_real_tool}

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                reply = msg.get("content", "")
                if reply.strip():
                    full_msgs.append({"role": "assistant", "content": reply})
                    return {"reply": reply, "stickers": sticker_paths, "has_real_tool": has_real_tool}
                return {"reply": "(嗯...小空在想)", "stickers": sticker_paths, "has_real_tool": has_real_tool}

            has_non_sticker = any(tc["function"]["name"] != "sticker" for tc in tool_calls)
            if has_non_sticker:
                non_sticker_rounds += 1

            # Execute each tool call
            for tc in tool_calls:
                tc_id = tc["id"]
                func = tc["function"]
                name = func["name"]
                try:
                    args = json.loads(func["arguments"])
                except json.JSONDecodeError:
                    args = {}
                if name == "sticker":
                    tag = args.get("tag", "")
                    path = stickers.search(tag) or stickers.random_sticker()
                    if path:
                        sticker_paths.append(path)
                        result = f"小空刚刚给主人发了一张 [{tag}] 表情包~ 在接下来的回复里用动作描写自然地提一下这张图（比如「*甩了张{tag}的表情过来*」），让主人知道小空自己意识到自己发了图。"
                    else:
                        result = f"表情包 [{tag}] 未找到，但不影响回复"
                elif name == "search":
                    result = self._web_search(args.get("query", ""))
                elif name == "remember_fact":
                    from . import memory
                    content = args.get("content", "")
                    tags = args.get("tags", "")
                    memory.remember(content, tags, session_name)
                    cnt = memory.count()
                    result = f"已记住 [{cnt}]: {content}"
                elif name == "recall_memory":
                    from . import memory
                    mems = memory.recall(args.get("query", ""))
                    if mems:
                        result = "\n".join(
                            f"[{m['id']}] {m['content']} (tags: {m['tags']})"
                            for m in mems
                        )
                    else:
                        result = "没有找到相关记忆"
                elif name == "browse_memories":
                    from . import memory
                    tags = memory.get_all_tags()
                    cnt = memory.count()
                    if tags:
                        result = f"记忆标签({cnt}条): " + ", ".join(tags)
                    else:
                        result = "还没有存储任何记忆"
                elif name == "recall_entity":
                    from . import memory
                    name = args.get("name", "")
                    e = memory.get_entity(name)
                    if not e:
                        result = f"未找到实体 [{name}]，可用标签: " + ", ".join(memory.get_all_tags())
                    else:
                        lines = [f"【{e['name']}】碎片 {e['fragment_count']} 条 / 叙事 {e['episode_count']} 条"]
                        if e.get("overview"):
                            lines.append(f"  概述: {e['overview']}")
                        eps = memory.get_entity_episodes(name, 3)
                        if eps:
                            lines.append("  叙事:")
                            for ep in eps:
                                lines.append(f"    · {ep['content']}")
                        result = "\n".join(lines)
                elif name == "add_todo":
                    from . import todo
                    text = args.get("text", "")
                    todo.get_model().add(text)
                    result = f"已添加「{text}」\n{todo.get_model().format_list()}"
                elif name == "list_todos":
                    from . import todo
                    result = todo.get_model().format_list()
                elif name == "check_todo":
                    from . import todo
                    idx = args.get("index", 0) - 1
                    items = todo.get_model().get_all()
                    if idx < 0 or idx >= len(items):
                        result = f"编号 {args.get('index', 0)} 超出范围"
                    else:
                        todo.get_model().toggle(idx)
                        result = f"已划掉「{items[idx]['text']}」\n{todo.get_model().format_list()}"
                elif name == "remove_todo":
                    from . import todo
                    idx = args.get("index", 0) - 1
                    items = todo.get_model().get_all()
                    if idx < 0 or idx >= len(items):
                        result = f"编号 {args.get('index', 0)} 超出范围"
                    else:
                        text = items[idx]["text"]
                        todo.get_model().remove(idx)
                        result = f"已删除「{text}」\n{todo.get_model().format_list()}"
                else:
                    result = tools.execute(name, args)
                    has_real_tool = True

                full_msgs.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": [tc],
                })
                full_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result,
                })

        return {"reply": "(工具调用太多次了，请换个方式问我~)", "stickers": sticker_paths, "has_real_tool": has_real_tool}
