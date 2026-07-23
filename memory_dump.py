import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kuu_bot import memory

print("=" * 60)
print("  KuuBot 记忆库总览")
print("=" * 60)

count = memory.count_fragments()

entities = memory.get_all_entities()
print(f"\n📊 碎片 {count} 条 | 叙事 {memory.get_all_episodes().__len__()} 条 | 实体 {len(entities)} 个")

print("\n━" * 40)
print("🏷️  标签")
print("━" * 40)
tags = memory.get_all_tags()
print("  " + ", ".join(tags) if tags else "  (无)")

print("\n━" * 40)
print("📦 实体画像")
print("━" * 40)
if not entities:
    print("  (无)")
for e in entities:
    icon = "🆕" if e["fragment_count"] < 3 else "📌"
    print(f"\n  {icon} {e['name']}  (碎片{e['fragment_count']} / 叙事{e['episode_count']})")
    if e.get("overview"):
        print(f"     概述: {e['overview']}")
    eps = memory.get_entity_episodes(e["name"], 3)
    if eps:
        for ep in eps:
            print(f"     · {ep['content'][:120]}")
        if len(eps) >= 3:
            print(f"     ... (共 {e['episode_count']} 条)")

print("\n━" * 40)
print("📝 未合并碎片")
print("━" * 40)
uncons = memory.get_unconsolidated_fragments()
if not uncons:
    print("  (全部已合并)")
for f in uncons:
    star = "★" if f["confidence"] >= 3 else "☆" if f["confidence"] >= 2 else "·"
    print(f"  {star} {f['content']}  (tags: {f['tags']}, conf: {f['confidence']})")

print("\n━" * 40)
print("📋 当前状态")
print("━" * 40)
states = memory.get_active_states()
if not states:
    print("  (无)")
for s in states:
    print(f"  [{s['category']}] {s['content']}  (TTL: {s['ttl_hours']}h)")

print("\n" + "=" * 60)
os.system("pause")
