# -*- coding: utf-8 -*-
"""cf_rails.py — рельсы контент-завода: STOP + append-only аудит + ГРОМКИЙ статус.
Форма переиспользована у Куратора (tools/kurator_rails.py): маленькие рельсы, которые
НЕ трогают функционал — только «оставить след» и «дать тормоз». Дельта прогона = новые
черновики в drafts/ (а не уроки, как у Куратора).

Смысл громкого статуса: владелец НИКОГДА не гадает «завод ходил или нет». _STATUS.md
переписывается на КАЖДОМ прогоне — и при успехе, и при провале. Прогон, убитый по
таймауту на полуслове, ловится на СТАРТЕ следующего (провизорная «идёт» осталась
незакрытой -> помечаем «не завершился»).

Дом можно переопределить env CF_BASE (для тестов, чтобы не сорить в боевую папку).
"""
import os, sys, datetime, json, glob

BASE = os.environ.get("CF_BASE") or os.path.dirname(os.path.abspath(__file__))
DRAFTS = os.path.join(BASE, "drafts")
STOP = os.path.join(BASE, "STOP")
AUDIT = os.path.join(BASE, "_audit.md")
STATUS = os.path.join(BASE, "_STATUS.md")
HIST = os.path.join(BASE, "_machine", "_status_history.json")


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def audit(event, detail=""):
    """Дозапись одной строки в дневник (append-only). Никогда не роняет вызывающего."""
    try:
        os.makedirs(BASE, exist_ok=True)
        fresh = not os.path.exists(AUDIT)
        e = str(event).replace("|", "/")
        d = str(detail).replace("|", "/")
        with open(AUDIT, "a", encoding="utf-8") as f:
            if fresh:
                f.write("# Контент-завод — аудит-дневник (append-only)\n\n"
                        "Дозапись; старое не стирается. Один прогон = строки со временем.\n\n"
                        "| Время | Событие | Детали |\n|---|---|---|\n")
            f.write("| %s | %s | %s |\n" % (_now(), e, d))
    except Exception:
        pass


def stopped():
    return os.path.exists(STOP)


def guard(who):
    """Вызвать ПЕРВЫМ. STOP стоит -> запись + выход (код 3). Иначе -> запись старта."""
    if stopped():
        audit("%s: ОСТАНОВЛЕН" % who, "стоит стоп-флаг %s" % STOP)
        print("[%s] STOP-флаг стоит (%s) — выхожу, ничего не делаю." % (who, STOP), flush=True)
        sys.exit(3)
    audit("%s: старт" % who, "")


def _dur(start, end):
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        d = datetime.datetime.strptime(end, fmt) - datetime.datetime.strptime(start, fmt)
        m, s = int(d.total_seconds() // 60), int(d.total_seconds() % 60)
        return ("%dм %dс" % (m, s)) if m else ("%dс" % s)
    except Exception:
        return ""


def _draft_names():
    """Все черновики в очереди (имена .json) — база дельты «что нового за прогон»."""
    try:
        return set(os.path.basename(p) for p in glob.glob(os.path.join(DRAFTS, "*.json")))
    except Exception:
        return set()


def _load_hist():
    try:
        with open(HIST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_hist(hist):
    try:
        os.makedirs(os.path.dirname(HIST), exist_ok=True)
        with open(HIST, "w", encoding="utf-8") as f:
            json.dump(hist[-30:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _write_status_md(verdict, start, end, steps, new, note=""):
    try:
        os.makedirs(BASE, exist_ok=True)
        dur = _dur(start, end)
        head = "## %s  ·  %s -> %s%s" % (verdict, start or "-", end or "…",
                                          (" (%s)" % dur) if dur else "")
        step_line = "  ·  ".join("%s: %s" % (k, v) for k, v in steps.items()) if steps else "-"
        new_line = ", ".join(new) if new else "нет новых"
        rows = []
        for h in reversed(_load_hist()[-8:]):
            t = (h.get("start") or "-")[5:16]
            d = ("+%d" % h["delta"]) if h.get("delta") else "-"
            rows.append("| %s | %s | %s | %s |" % (t, h.get("verdict", "-"), d, h.get("note") or "-"))
        if not rows:
            rows = ["| - | - | - | - |"]
        lines = [
            "# Контент-завод — статус последнего прогона",
            "",
            head,
            "",
            "- **Шаги:** %s" % step_line,
            "- **Новые черновики:** %s" % new_line,
            "- **Заметка:** %s" % (note or "-"),
            "",
            "> Файл переписывается КАЖДЫЙ прогон — и при успехе, и при провале.",
            "> Если тут висит «идёт» дольше ~часа — прогон убит по таймауту (следующий прогон отметит это в истории ниже).",
            "> Черновики ждут АПРУВА владельца — завод НЕ публикует сам.",
            "",
            "---",
            "### Последние прогоны",
            "| Время | Итог | Δ черновиков | Заметка |",
            "|---|---|---|---|",
        ] + rows + [""]
        with open(STATUS, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


def status_start(who="run"):
    """Отметить старт: провизорная «идёт» + ловля недобитого прошлого прогона. Возвращает rec."""
    rec = {"start": _now(), "before": sorted(_draft_names())}
    try:
        hist = _load_hist()
        if hist and not hist[-1].get("finished"):
            hist[-1]["verdict"] = "не завершился"
            hist[-1]["note"] = "убит/завис — нет финала (таймаут?)"
            hist[-1]["finished"] = True
        hist.append({"start": rec["start"], "end": None, "verdict": "идёт",
                     "delta": 0, "new": [], "note": "прогон идёт", "finished": False})
        _save_hist(hist)
    except Exception:
        pass
    _write_status_md("идёт", rec["start"], None, {}, [], note="прогон запущен, ждём завершения")
    return rec


def status_end(rec, verdict, steps, note=""):
    """Финал: считает дельту черновиков, пишет громкий _STATUS.md + закрывает историю."""
    try:
        new = sorted(_draft_names() - set(rec.get("before", [])))
        end = _now()
        entry = {"start": rec.get("start"), "end": end, "verdict": verdict,
                 "delta": len(new), "new": new, "note": note, "finished": True}
        hist = _load_hist()
        if hist and not hist[-1].get("finished") and hist[-1].get("start") == rec.get("start"):
            hist[-1] = entry
        else:
            hist.append(entry)
        _save_hist(hist)
        _write_status_md(verdict, rec.get("start"), end, steps, new, note)
    except Exception:
        pass
