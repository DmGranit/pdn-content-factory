# -*- coding: utf-8 -*-
"""deliver.py — доставщик: публикует ОДОБРЕННОЕ по расписанию.

Запускается планировщиком часто (раз в час). Сам решает, наступил ли слот — так надёжнее
двух задач в фиксированное время: если ПК был выключен в 10:00 и включился в 14:00,
пост всё равно выйдет, а не потеряется. Двойную публикацию не допускает журнал доставки.

ЧЕЛОВЕК-ГЕЙТ НЕ ОБХОДИТСЯ: публикуется только то, что владелец одобрил своей рукой в пульте.
Доставщик решает «когда», человек — «что». Просроченное одобрение и правку после одобрения
он не публикует, а возвращает в drafts/ на пересмотр.

Запуск вручную:  python deliver.py          — отработать наступившие слоты
                 python deliver.py --dry    — показать, что сделал бы, ничего не публикуя
"""
import os, sys, json, shutil, subprocess, re

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cf_rails as R
import cf_schedule as S

PUBLISHER = os.path.join(HERE, "publisher", "publish_telegram.py")
DRY = "--dry" in sys.argv


def _move_pair(slug, src, dest):
    """Переносит пост и всё, что к нему прилипло (картинка, предпросмотр, снапшот)."""
    os.makedirs(dest, exist_ok=True)
    moved = []
    for name in os.listdir(src):
        if slug in name:
            try:
                shutil.move(os.path.join(src, name), os.path.join(dest, name))
                moved.append(name)
            except Exception:
                pass
    return moved


def _return_to_drafts(item, reason):
    """Негодный пост — назад в очередь черновиков, с явной причиной в имени снапшота."""
    slug = item["slug"]
    if DRY:
        return "вернул бы в drafts/ (%s)" % reason
    os.makedirs(S.DRAFTS, exist_ok=True)
    for name in os.listdir(S.APPROVED):
        if slug not in name:
            continue
        src = os.path.join(S.APPROVED, name)
        if name.endswith(".approval.json"):
            try:
                os.remove(src)          # одобрение аннулировано, снапшот не нужен
            except Exception:
                pass
            continue
        try:
            shutil.move(src, os.path.join(S.DRAFTS, name))
        except Exception:
            pass
    R.audit("deliver: одобрение снято", "%s — %s" % (slug, reason))
    return "возвращён в drafts/ (%s)" % reason


def publish(item, slot):
    """Публикация одного поста. Возвращает (ok, note)."""
    slug, jpath = item["slug"], item["json_path"]
    if DRY:
        return True, "СУХОЙ ПРОГОН: опубликовал бы %s в слот %s" % (slug, slot["id"])
    try:
        p = subprocess.run([sys.executable, PUBLISHER, jpath], cwd=HERE,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except Exception as e:
        return False, "публикатор не запустился: %s" % str(e)[:160]
    out = ((p.stdout or "") + " " + (p.stderr or "")).replace("\n", " ")
    m = re.search(r"message_id[:\s]+(\d+)", out)
    if p.returncode == 0 and m:
        _move_pair(slug, S.APPROVED, S.PUBLISHED)
        return True, "message_id %s" % m.group(1)
    return False, "rc=%s %s" % (p.returncode, out[-200:])


def main():
    R.guard("deliver")
    cfg = S.load_schedule()
    now = S.now_channel(cfg)
    slots = S.due_slots(cfg, now)

    # Негодное чистим всегда, даже когда слотов нет: очередь не должна копить мусор.
    cleaned = []
    for item in S.approved_queue(cfg):
        if item["problem"]:
            cleaned.append("%s: %s" % (item["slug"], _return_to_drafts(item, item["problem"])))

    if not slots:
        note = "слотов на сейчас нет (%s МСК)" % now.strftime("%a %H:%M")
        if cleaned:
            note += " · снято одобрений: %d" % len(cleaned)
        print("[deliver] %s" % note)
        R.audit("deliver: холостой ход", note)
        return

    rec = R.status_start("deliver")
    steps, results = {}, []
    for slot in slots:
        queue = S.ready_queue(cfg)
        need = int(slot.get("require_queue_min", 0) or 0)
        if not queue:
            S.log_delivery(slot, "skipped", note="очередь одобренных пуста")
            steps[slot["id"]] = "пропущен — нечего публиковать"
            results.append("%s: очередь пуста" % slot["id"])
            continue
        if need and len(queue) < need:
            S.log_delivery(slot, "skipped", note="резервный слот: в очереди %d < %d" % (len(queue), need))
            steps[slot["id"]] = "резерв не сработал (%d < %d)" % (len(queue), need)
            results.append("%s: резерв не сработал" % slot["id"])
            continue

        item = queue[0]                        # FIFO: старое одобренное уходит первым
        ok, note = publish(item, slot)
        if ok:
            S.log_delivery(slot, "published", slug=item["slug"], note=note)
            steps[slot["id"]] = "опубликован %s" % item["slug"]
            results.append("%s → %s (%s)" % (slot["id"], item["slug"], note))
            R.audit("deliver: опубликовано", "%s · слот %s · %s" % (item["slug"], slot["id"], note))
            if not DRY:
                try:
                    subprocess.run([sys.executable, os.path.join(HERE, "news_writer.py"),
                                    os.path.join(S.PUBLISHED, item["slug"] + ".json"),
                                    "--tag", slot.get("rubric", "")],
                                   cwd=HERE, capture_output=True, text=True, timeout=60)
                except Exception:
                    pass
        else:
            S.log_delivery(slot, "failed", slug=item["slug"], note=note)
            steps[slot["id"]] = "СБОЙ публикации"
            results.append("%s: СБОЙ — %s" % (slot["id"], note))
            R.audit("deliver: СБОЙ публикации", "%s · %s" % (item["slug"], note))

    verdict = "готово" if all("СБОЙ" not in r for r in results) else "частично"
    if cleaned:
        steps["снято одобрений"] = str(len(cleaned))
    R.status_end(rec, verdict, steps, " · ".join(results))
    print("[deliver] %s — %s" % (verdict, " · ".join(results)))


if __name__ == "__main__":
    main()
