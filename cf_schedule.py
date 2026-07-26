# -*- coding: utf-8 -*-
"""cf_schedule.py — общая логика расписания и одобренной очереди.

Три вещи, которые нужны и пульту, и доставщику, и заводу:
  1) чтение сетки слотов (schedule.json, время — по Москве);
  2) снапшот одобрения: штамп времени + sha256 текста поста (правка после
     одобрения ДОЛЖНА снимать одобрение — иначе в канал уйдёт не то, что смотрел человек);
  3) журнал доставки: какой слот в какой день уже отработан (защита от двойной публикации,
     если скрипт запустится дважды).

Имена полей взяты из спецификации редакторской панели (approval_snapshot, slot,
scheduled_at) — чтобы будущий переезд был переносом данных, а не переписыванием.
"""
import os, sys, json, hashlib, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cf_env  # noqa: F401  — подтягивает .env в окружение до чтения переменных

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("CF_BASE") or HERE
DRAFTS = os.path.join(BASE, "drafts")
APPROVED = os.path.join(BASE, "approved")
PUBLISHED = os.path.join(BASE, "published")
REJECTED = os.path.join(BASE, "rejected")
SCHEDULE = os.path.join(BASE, "schedule.json")
DELIVERY_LOG = os.path.join(BASE, "_machine", "_delivery_log.json")

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---------- расписание ----------

def load_schedule():
    """Сетка слотов. Нет файла/битый — пустое расписание (доставщик просто ничего не сделает)."""
    try:
        with open(SCHEDULE, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return {"timezone": "Europe/Moscow", "approval_ttl_days": 5, "slots": []}
    cfg.setdefault("timezone", "Europe/Moscow")
    cfg.setdefault("approval_ttl_days", 5)
    cfg.setdefault("slots", [])
    return cfg


def channel_tz(cfg=None):
    cfg = cfg or load_schedule()
    try:
        return ZoneInfo(cfg.get("timezone", "Europe/Moscow"))
    except Exception:
        return ZoneInfo("Europe/Moscow")


def now_channel(cfg=None):
    """Текущее время в таймзоне АУДИТОРИИ, а не машины (владелец может быть где угодно)."""
    return datetime.datetime.now(channel_tz(cfg))


def due_slots(cfg=None, now=None):
    """Слоты, чьё время сегодня уже наступило и которые ещё не отработаны.

    Проверяем «наступило», а не «ровно сейчас»: если ПК был выключен в 10:00 и включился
    в 14:00 — слот всё ещё считается due и пост выйдет с опозданием, а не потеряется.
    Слоты прошлых дней не догоняем (вчерашняя новость сегодня уже не новость).
    """
    cfg = cfg or load_schedule()
    now = now or now_channel(cfg)
    today_key = now.strftime("%Y-%m-%d")
    wd = WEEKDAYS[now.weekday()]
    done = delivered_today(today_key)
    out = []
    for s in cfg.get("slots", []):
        if not s.get("active", True) or s.get("weekday") != wd or s.get("id") in done:
            continue
        try:
            hh, mm = str(s.get("time", "")).split(":")
            slot_dt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except Exception:
            continue
        if now >= slot_dt:
            out.append(dict(s, scheduled_at=slot_dt.isoformat(), date_key=today_key))
    return out


# ---------- снапшот одобрения ----------

def content_hash(json_path):
    """sha256 того, что реально уйдёт в канал (тексты площадок + картинка).

    Хешируем не файл целиком, а публикуемую суть: служебные поля (пути, служебные пометки)
    могут меняться, а одобрение снимать должна только правка САМОГО ПОСТА.
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return ""
    plat = d.get("platforms", {}) or {}
    payload = json.dumps({
        "tg": (plat.get("telegram", {}) or {}).get("content", ""),
        "vk": (plat.get("vk", {}) or {}).get("content", ""),
        "image": os.path.basename(str(d.get("image_file") or "")) or (d.get("image_url") or ""),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approval_path(slug):
    return os.path.join(APPROVED, slug + ".approval.json")


def write_approval(slug, ttl_days=None, approved_by="owner"):
    """Пишет снапшот одобрения рядом с постом в approved/. Возвращает словарь снапшота."""
    cfg = load_schedule()
    ttl = int(ttl_days if ttl_days is not None else cfg.get("approval_ttl_days", 5))
    now = now_channel(cfg)
    snap = {
        "slug": slug,
        "approved_at": now.isoformat(),
        "approved_by": approved_by,
        "expires_at": (now + datetime.timedelta(days=ttl)).isoformat(),
        "content_hash": content_hash(os.path.join(APPROVED, slug + ".json")),
        "state": "approved",
    }
    os.makedirs(APPROVED, exist_ok=True)
    with open(approval_path(slug), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    return snap


def read_approval(slug):
    try:
        with open(approval_path(slug), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def approved_queue(cfg=None):
    """Одобренные посты, готовые к выходу — старые первыми (FIFO).

    Возвращает список словарей: slug · json_path · snapshot · problem.
    problem заполняется, если пост НЕ годен: 'expired' (просрочено одобрение) или
    'modified' (текст правили после одобрения). Такие доставщик не публикует.
    """
    cfg = cfg or load_schedule()
    now = now_channel(cfg)
    items = []
    if not os.path.isdir(APPROVED):
        return items
    for name in sorted(os.listdir(APPROVED)):
        if not name.endswith(".json") or name.endswith(".approval.json"):
            continue
        slug = name[:-5]
        jpath = os.path.join(APPROVED, name)
        snap = read_approval(slug)
        problem = None
        if not snap:
            problem = "no_approval"
        else:
            try:
                if now > datetime.datetime.fromisoformat(snap["expires_at"]):
                    problem = "expired"
            except Exception:
                pass
            if not problem and snap.get("content_hash") and content_hash(jpath) != snap["content_hash"]:
                problem = "modified"
        items.append({"slug": slug, "json_path": jpath, "snapshot": snap,
                      "problem": problem,
                      "approved_at": (snap or {}).get("approved_at", "")})
    items.sort(key=lambda x: x["approved_at"] or "")
    return items


def ready_queue(cfg=None):
    """Только годные к публикации (без просрочек и правок)."""
    return [i for i in approved_queue(cfg) if not i["problem"]]


# ---------- журнал доставки ----------

def _load_log():
    try:
        with open(DELIVERY_LOG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_log(log):
    try:
        os.makedirs(os.path.dirname(DELIVERY_LOG), exist_ok=True)
        with open(DELIVERY_LOG, "w", encoding="utf-8") as f:
            json.dump(log[-200:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def delivered_today(date_key):
    """id слотов, уже отработанных в этот день (успешно или намеренно пропущенных)."""
    return {e.get("slot_id") for e in _load_log()
            if e.get("date_key") == date_key and e.get("state") in ("published", "skipped")}


def log_delivery(slot, state, slug=None, note=""):
    """Дозапись факта: слот отработан. state: published | skipped | failed."""
    log = _load_log()
    log.append({
        "date_key": slot.get("date_key"),
        "slot_id": slot.get("id"),
        "rubric": slot.get("rubric"),
        "scheduled_at": slot.get("scheduled_at"),
        "delivered_at": now_channel().isoformat(),
        "state": state,
        "slug": slug,
        "note": note,
    })
    _save_log(log)
