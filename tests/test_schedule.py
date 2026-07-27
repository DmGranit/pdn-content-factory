# -*- coding: utf-8 -*-
"""Проверка логики расписания и одобренной очереди.

Работает в одноразовой песочнице — боевые drafts/approved/published не трогает,
ключи и сеть не нужны, ничего никуда не публикуется.

Запуск из корня проекта:  python tests/test_schedule.py
"""
import os, sys, json, shutil, tempfile, datetime

sys.stdout.reconfigure(encoding="utf-8")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAND = tempfile.mkdtemp(prefix="cf_test_")
os.environ["CF_BASE"] = SAND
shutil.copy(os.path.join(REPO, "schedule.json"), os.path.join(SAND, "schedule.json"))
sys.path.insert(0, REPO)
import cf_schedule as S

ok = fail = 0
def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1; print("  PASS  %s" % name)
    else:
        fail += 1; print("  FAIL  %s  %s" % (name, detail))

post = {
    "schema_version": "social-content/v1",
    "source": {"title": "Тестовая новость", "url": "https://example.org/x", "published_at": "2026-07-27"},
    "platforms": {"telegram": {"content": "Текст поста для канала"}, "vk": {"content": "Текст VK"}},
}
os.makedirs(S.APPROVED, exist_ok=True)
p = os.path.join(S.APPROVED, "2026-07-27-test.json")
json.dump(post, open(p, "w", encoding="utf-8"), ensure_ascii=False)

print("\n1. Снапшот одобрения")
snap = S.write_approval("2026-07-27-test")
check("хеш посчитан", len(snap["content_hash"]) == 64)
check("срок годности +5 дней",
      (datetime.datetime.fromisoformat(snap["expires_at"]) -
       datetime.datetime.fromisoformat(snap["approved_at"])).days == 5)
check("пост годен к выходу", len(S.ready_queue()) == 1)

print("\n2. Правка текста ПОСЛЕ одобрения снимает одобрение")
post["platforms"]["telegram"]["content"] = "ПОДМЕНЁННЫЙ текст"
json.dump(post, open(p, "w", encoding="utf-8"), ensure_ascii=False)
q = S.approved_queue()
check("помечен как modified", q[0]["problem"] == "modified", q[0]["problem"])
check("к публикации не годен", len(S.ready_queue()) == 0)

print("\n3. Служебные поля одобрение НЕ снимают")
post["platforms"]["telegram"]["content"] = "Текст поста для канала"   # вернули как было
post["image_prompt"] = "добавили служебное поле"
json.dump(post, open(p, "w", encoding="utf-8"), ensure_ascii=False)
check("снова годен", len(S.ready_queue()) == 1)

print("\n4. Просроченное одобрение не публикуется")
snap["expires_at"] = (S.now_channel() - datetime.timedelta(days=1)).isoformat()
json.dump(snap, open(S.approval_path("2026-07-27-test"), "w", encoding="utf-8"), ensure_ascii=False)
check("помечен как expired", S.approved_queue()[0]["problem"] == "expired")
check("к публикации не годен", len(S.ready_queue()) == 0)

print("\n5. Слоты по дням недели (время — МСК)")
mon10 = datetime.datetime(2026, 7, 27, 10, 30, tzinfo=S.channel_tz())   # понедельник
check("пн 10:30 -> слот mon-price наступил",
      [s["id"] for s in S.due_slots(now=mon10)] == ["mon-price"])
mon09 = mon10.replace(hour=9, minute=0)
check("пн 09:00 -> слотов нет", S.due_slots(now=mon09) == [])
tue19 = datetime.datetime(2026, 7, 28, 19, 0, tzinfo=S.channel_tz())    # вторник, резерв
check("вт 19:00 -> резервный слот виден", [s["id"] for s in S.due_slots(now=tue19)] == ["tue-reserve"])
check("у резерва есть порог очереди",
      S.due_slots(now=tue19)[0].get("require_queue_min") == 3)

print("\n6. Догоняем пропущенное в тот же день, но не вчерашнее")
mon23 = mon10.replace(hour=23, minute=50)
check("пн 23:50 -> слот всё ещё due (ПК включили поздно)",
      [s["id"] for s in S.due_slots(now=mon23)] == ["mon-price"])
tue09 = datetime.datetime(2026, 7, 28, 9, 0, tzinfo=S.channel_tz())
check("вт 09:00 -> вчерашний слот не догоняем", S.due_slots(now=tue09) == [])

print("\n7. Журнал доставки защищает от двойной публикации")
slot = S.due_slots(now=mon10)[0]
S.log_delivery(slot, "published", slug="2026-07-27-test", note="тест")
check("после записи слот больше не due", S.due_slots(now=mon10) == [])

print("\n%d PASS, %d FAIL" % (ok, fail))
shutil.rmtree(SAND, ignore_errors=True)
sys.exit(1 if fail else 0)
