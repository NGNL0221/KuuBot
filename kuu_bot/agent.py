import json
import requests
import datetime
from . import tools


DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
MAX_TOOL_ROUNDS = 8

ENV_CTX = """
当前环境: Windows 10/11, Python 3.10
默认工作目录: D:/妙妙工具/KuuBot/
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

⚠️ 禁止用 bash 打开浏览器或任何 GUI 程序（start、explorer 等）。搜索问题让 DeepSeek 自动联网，不要手动弹出浏览器。
"""


class Agent:
    def __init__(self, api_key: str, persona: str):
        self._key = api_key
        self._persona = persona

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
        sys_content += casual_note + "\n" + tools.TOOLS_DESC
        full_msgs = [{"role": "system", "content": sys_content}]

        # Take last 100 messages, trim summary from user-facing msgs
        recent = messages[-100:]
        full_msgs.extend(recent)

        for _ in range(MAX_TOOL_ROUNDS):
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
                        "web_search_options": {"search_mode": "on"},
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
                return {"reply": f"(小空出了点问题: {e})"}

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                reply = msg.get("content", "")
                if reply.strip():
                    full_msgs.append({"role": "assistant", "content": reply})
                    return {"reply": reply}
                return {"reply": "(嗯...小空在想)"}

            # Execute each tool call
            for tc in tool_calls:
                tc_id = tc["id"]
                func = tc["function"]
                name = func["name"]
                try:
                    args = json.loads(func["arguments"])
                except json.JSONDecodeError:
                    args = {}
                result = tools.execute(name, args)

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

        return {"reply": "(工具调用太多次了，请换个方式问我~)"}
