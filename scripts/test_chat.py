r"""P1 端到端测试：聊天抽取记录 → 确认卡片 → 确认入账。

用法：server\.venv\Scripts\python.exe scripts\test_chat.py [消息内容]
"""
import json
import sys
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8001/api"


def post(path: str, body: dict):
    req = urllib.request.Request(
        BASE + path, method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def stream_message(chat_id: int, content: str):
    """消费 SSE 流，返回 (tokens, cards, done)。"""
    req = urllib.request.Request(
        f"{BASE}/chats/{chat_id}/messages", method="POST",
        data=json.dumps({"content": content, "request_id": str(uuid.uuid4())}).encode(),
        headers={"Content-Type": "application/json"},
    )
    tokens, cards, done = [], [], {}
    with urllib.request.urlopen(req, timeout=180) as r:
        event = None
        for raw in r:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                data = json.loads(line[6:])
                if event == "token":
                    tokens.append(data["text"])
                elif event == "record_card":
                    cards.append(data)
                elif event == "done":
                    done = data
    return "".join(tokens), cards, done


message = sys.argv[1] if len(sys.argv) > 1 else "今晚喝了杯三分糖的奶茶，还游了45分钟泳"

chat = post("/chats", {})
print(f"chat id={chat['id']} date={chat['date']} opener={chat.get('opener')!r}")

print(f"\n>>> 用户：{message}")
text, cards, done = stream_message(chat["id"], message)
print(f"<<< AI：{text}")
print(f"    cards={len(cards)} done={done}")

for i, c in enumerate(cards, 1):
    print(f"\n[卡片{i}] {json.dumps(c, ensure_ascii=False, indent=2)}")
    # 测试确认入账
    if "--confirm" in sys.argv:
        result = post(f"/chats/{chat['id']}/confirm", {
            "draft": c["draft"], "message_id": done.get("message_id"),
        })
        print(f"[入账] {json.dumps(result, ensure_ascii=False)}")
