# -*- coding: utf-8 -*-
"""news_writer.py — переносит опубликованный пост в новостную ленту сайта.

ГОТОВИТ, НО НЕ ПУШИТ. Пишет обновлённый news.json в репозиторий лендинга и говорит
«готово к пушу». Коммит и push на боевой сайт — рукой владельца: автомату право записи
в живой продукт не выдаём (решение владельца 2026-07-27).

Где лежит репо сайта — переменная окружения CF_SITE_REPO (см. local.bat). Не задана или
папки нет → скрипт молча ничего не делает: доставка постов в канал от этого не страдает.

Запуск:  python news_writer.py <путь_к_опубликованному_json> [--tag "Рубрика"]
         python news_writer.py --status     — что в ленте сейчас, есть ли неотправленное
"""
import os, sys, json, re, datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cf_env  # noqa: F401  — .env -> окружение (кириллический путь к сайту живёт там)

SITE_REPO = os.environ.get("CF_SITE_REPO", "")
NEWS_FILE = os.path.join(SITE_REPO, "news.json") if SITE_REPO else ""
MAX_ITEMS = int(os.environ.get("CF_NEWS_MAX", "12"))     # лента сайта — витрина, не архив
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️←-⇿⬀-⯿]+")


def make_summary(post, limit=320):
    """Короткая выжимка для карточки на сайте.

    Приоритет — поле site_summary (его пишет агент). Нет его — берём первый содержательный
    абзац поста: срезаем эмодзи-крючок и футер-CTA, они на сайте не нужны.
    """
    ready = (post.get("site_summary") or "").strip()
    if ready:
        return ready
    text = ((post.get("platforms", {}) or {}).get("telegram", {}) or {}).get("content", "")
    paras = []
    for p in text.split("\n"):
        p = p.strip()
        if not p or "pdn-compliance-os.onrender.com" in p:   # футер-CTA — мимо
            continue
        p = EMOJI.sub("", p).strip(" —-·")
        if len(p) > 40:
            paras.append(p)
    body = " ".join(paras[:2]).strip()
    if len(body) > limit:
        cut = body[:limit].rsplit(" ", 1)[0]
        body = cut + "…"
    return body


def to_news_item(post, tag=""):
    src = post.get("source", {}) or {}
    raw_date = str(src.get("published_at") or "")
    try:
        d = datetime.date.fromisoformat(raw_date).strftime("%d.%m.%Y")
    except Exception:
        d = datetime.date.today().strftime("%d.%m.%Y")
    return {
        "date": d,
        "tag": tag or "152-ФЗ",
        "title": (src.get("title") or "").strip(),
        "summary": make_summary(post),
        "source": src.get("publisher") or "Первоисточник",
        "url": src.get("url") or "",
    }


def status():
    if not NEWS_FILE or not os.path.exists(NEWS_FILE):
        print("[news] репо сайта не задан (CF_SITE_REPO) или news.json не найден — лента не ведётся")
        return
    with open(NEWS_FILE, encoding="utf-8") as f:
        items = json.load(f)
    print("[news] в ленте %d пунктов, файл: %s" % (len(items), NEWS_FILE))
    for i in items[:3]:
        print("   · %s | %s | %s" % (i.get("date"), i.get("tag"), (i.get("title") or "")[:60]))


def main():
    if "--status" in sys.argv:
        return status()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tag = ""
    if "--tag" in sys.argv:
        try:
            tag = sys.argv[sys.argv.index("--tag") + 1]
        except IndexError:
            pass
    if not args:
        sys.exit("Укажи JSON опубликованного поста:  python news_writer.py <путь> [--tag Рубрика]")
    if not NEWS_FILE or not os.path.isdir(SITE_REPO):
        print("[news] CF_SITE_REPO не задан или папка не найдена — пропускаю (это не ошибка)")
        return

    post = json.load(open(args[0], encoding="utf-8"))
    item = to_news_item(post, tag)
    if not item["title"]:
        print("[news] у поста нет source.title — в ленту не добавляю")
        return

    try:
        items = json.load(open(NEWS_FILE, encoding="utf-8"))
        if not isinstance(items, list):
            items = []
    except Exception:
        items = []

    if any((i.get("url") and i["url"] == item["url"]) or i.get("title") == item["title"] for i in items):
        print("[news] такой пункт уже в ленте — пропускаю")
        return

    items.insert(0, item)
    items = items[:MAX_ITEMS]
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("[news] ✅ лента обновлена: «%s» (тег: %s)" % (item["title"][:60], item["tag"]))
    print("[news] ⚠️  ГОТОВО К ПУШУ — коммит и push делает владелец своей рукой:")
    print('       cd "%s" && git add news.json && git commit -m "Новости: %s" && git push'
          % (SITE_REPO, item["title"][:50]))


if __name__ == "__main__":
    main()
