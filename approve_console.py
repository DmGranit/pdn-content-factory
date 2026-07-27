# -*- coding: utf-8 -*-
"""approve_console.py — локальный ПУЛЬТ АПРУВА черновиков контент-завода.

Человек-гейт кликом. Владелец решает ЧТО выйдет, расписание решает КОГДА:
  «Одобрить»  -> пост уезжает в approved/ со снапшотом одобрения (штамп времени + хеш
                 текста), дальше его заберёт deliver.py в ближайший слот сетки;
  «Отклонить» -> в rejected/;
  «Опубликовать сейчас» -> немедленно, мимо расписания (когда новость горит).

Правка текста после одобрения снимает одобрение (хеш не сойдётся) — в канал не может уйти
не то, что смотрел человек. Секреты пульт не трогает: их берёт публикатор сам.
Локально: http://127.0.0.1:5055 . Остановить — Ctrl+C в окне.
"""
import os, sys, glob, json, base64, subprocess, shutil, re
from flask import Flask, request, redirect, render_template_string, url_for

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cf_schedule as S
import cf_rails as R

DRAFTS = os.path.join(HERE, "drafts")
APPROVED = os.path.join(HERE, "approved")
PUBLISHED = os.path.join(HERE, "published")
REJECTED = os.path.join(HERE, "rejected")
PUBLISHER = os.path.join(HERE, "publisher", "publish_telegram.py")

app = Flask(__name__)


def next_slots(limit=3):
    """Ближайшие слоты сетки — чтобы владелец видел, КОГДА выйдет то, что он одобряет."""
    import datetime
    cfg = S.load_schedule()
    now = S.now_channel(cfg)
    out = []
    for day in range(0, 8):
        d = now + datetime.timedelta(days=day)
        wd = S.WEEKDAYS[d.weekday()]
        for s in sorted(cfg.get("slots", []), key=lambda x: x.get("time", "")):
            if not s.get("active", True) or s.get("weekday") != wd:
                continue
            try:
                hh, mm = str(s["time"]).split(":")
                when = d.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            except Exception:
                continue
            if when <= now:
                continue
            names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
            out.append({"when": "%s %s МСК" % (names[when.weekday()], when.strftime("%d.%m %H:%M")),
                        "rubric": s.get("rubric", ""),
                        "reserve": bool(s.get("require_queue_min"))})
            if len(out) >= limit:
                return out
    return out


def load_queue():
    """Одобренное, ждущее своего слота (для нижней панели пульта)."""
    out = []
    for i in S.approved_queue():
        snap = i.get("snapshot") or {}
        out.append({
            "slug": i["slug"],
            "approved_at": (snap.get("approved_at") or "")[:16].replace("T", " "),
            "expires_at": (snap.get("expires_at") or "")[:10],
            "problem": i.get("problem"),
        })
    return out


def load_drafts():
    items = []
    for p in sorted(glob.glob(os.path.join(DRAFTS, "*.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        slug = os.path.splitext(os.path.basename(p))[0]
        img = d.get("image_file")
        img_uri = None
        if img and os.path.exists(img):
            ext = "webp" if str(img).lower().endswith("webp") else "png"
            img_uri = "data:image/%s;base64,%s" % (ext, base64.b64encode(open(img, "rb").read()).decode())
        plat = d.get("platforms", {}) or {}
        items.append({
            "slug": slug,
            "tg": (plat.get("telegram", {}) or {}).get("content", ""),
            "vk": (plat.get("vk", {}) or {}).get("content", ""),
            "source": d.get("source", {}) or {},
            "img_uri": img_uri,
        })
    return items


def _move(slug, dest, src=None):
    """Переносит пост и всё, что к нему прилипло (картинка, предпросмотр). src по умолч. — drafts/."""
    src = src or DRAFTS
    os.makedirs(dest, exist_ok=True)
    pats = glob.glob(os.path.join(src, slug + ".*")) + glob.glob(os.path.join(src, "*" + slug + ".*"))
    for p in set(pats):
        if p.endswith(".approval.json"):
            continue                      # снапшот одобрения за постом не ездит
        try:
            shutil.move(p, os.path.join(dest, os.path.basename(p)))
        except Exception:
            pass


TEMPLATE = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Пульт апрува · контент-завод</title>
<style>
 body{margin:0;background:#0f1117;color:#e8eaed;font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:820px;margin:0 auto;padding:22px 16px 70px}
 h1{font-size:20px;margin:0 0 2px} .sub{color:#9aa0aa;font-size:13px;margin-bottom:16px}
 .msg{background:#12351f;border:1px solid #1f5a34;color:#9ff0b8;border-radius:12px;padding:12px 16px;margin:14px 0;font-size:14px;white-space:pre-wrap}
 .msg.err{background:#3a1414;border-color:#6a1f1f;color:#ff9b9b}
 .card{background:#171a22;border:1px solid #262b36;border-radius:16px;margin:18px 0;overflow:hidden}
 .card h2{font-size:14px;margin:0;padding:14px 18px;border-bottom:1px solid #262b36;color:#8ab4ff}
 img.hero{display:block;width:100%;height:auto}
 .body{padding:16px 18px}
 .lbl{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#6b7280;margin:14px 0 6px}
 .post{white-space:pre-wrap;font-size:15px;background:#0b0d12;border:1px solid #23283340;border-radius:10px;padding:12px 14px}
 .src{font-size:12.5px;color:#9aa0aa;margin-top:12px}
 .actions{display:flex;gap:10px;flex-wrap:wrap;padding:14px 18px;border-top:1px solid #262b36;background:#12141b}
 button{border:0;border-radius:10px;padding:11px 18px;font-size:14px;font-weight:600;cursor:pointer}
 .ok{background:#1f9d55;color:#fff} .ok:hover{background:#25b365}
 .now{background:#3a2f16;color:#ffce7a;border:1px solid #6b5320} .now:hover{background:#4a3c1c}
 .no{background:#2a2f3a;color:#cbd2dc} .no:hover{background:#3a4150}
 .mini{background:#232833;color:#9aa0aa;font-size:12px;padding:6px 10px}
 .empty{color:#8b93a0;text-align:center;padding:50px 0}
 a{color:#6cb6ff}
 .gate{font-size:12px;color:#ffce7a;margin:0 18px 6px}
 .plan{background:#12161f;border:1px solid #232833;border-radius:12px;padding:12px 16px;margin:14px 0;font-size:13px;color:#9aa0aa}
 .plan b{color:#8ab4ff;font-weight:600}
 .queue{margin-top:28px;border-top:1px solid #262b36;padding-top:14px}
 .queue h3{font-size:14px;color:#8ab4ff;margin:0 0 10px}
 .qrow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:8px 12px;background:#12161f;border:1px solid #232833;border-radius:10px;margin-bottom:8px;font-size:13px}
 .qrow.bad{border-color:#6a4a1f;background:#1d1710}
 .qrow .meta{color:#8b93a0;font-size:12px;margin-left:auto}
</style></head><body><div class=wrap>
<h1>🏭 Пульт апрува · @pdn152fz_check</h1>
<div class=sub>Черновики от контент-завода. В канал выходит <b>только одобренное тобой</b>, только Telegram. VK — скопируй вручную.</div>
{% if slots %}
<div class=plan>📅 Ближайшие слоты:
{% for s in slots %} <b>{{ s.when }}</b> — {{ s.rubric }}{% if s.reserve %} (резерв){% endif %}{{ "," if not loop.last }}{% endfor %}
</div>
{% endif %}
{% if msg %}<div class="msg {{ 'err' if not msg.startswith('✅') else '' }}">{{ msg }}</div>{% endif %}
{% if not drafts %}<div class=empty>Очередь пуста — новых черновиков нет.<br>Их кладёт субагент content-factory.</div>{% endif %}
{% for d in drafts %}
<div class=card>
  <h2>📝 {{ d.source.title or d.slug }}</h2>
  {% if d.img_uri %}<img class=hero src="{{ d.img_uri }}" alt="картинка">{% endif %}
  <div class=body>
    <div class=lbl>📢 Telegram (опубликуется)</div>
    <div class=post>{{ d.tg }}</div>
    {% if d.vk %}<div class=lbl>🅥 VK (скопировать вручную)</div>
    <div class=post>{{ d.vk }}</div>{% endif %}
    {% if d.source.url %}<div class=src>Источник: <a href="{{ d.source.url }}" target=_blank>{{ d.source.url }}</a></div>{% endif %}
  </div>
  <div class=gate>Одобрение = разрешение выйти в БОЕВОЙ канал. Проверь факты и картинку.</div>
  <div class=actions>
    <form method=post action="/approve" onsubmit="return confirm('Одобрить? Пост выйдет в канал в ближайший слот расписания.');">
      <input type=hidden name=slug value="{{ d.slug }}">
      <button class=ok>✅ Одобрить → в очередь на публикацию</button>
    </form>
    <form method=post action="/publish-now" onsubmit="return confirm('ОПУБЛИКОВАТЬ ПРЯМО СЕЙЧАС в @pdn152fz_check, мимо расписания?');">
      <input type=hidden name=slug value="{{ d.slug }}">
      <button class=now>⚡ Опубликовать сейчас</button>
    </form>
    <form method=post action="/reject" onsubmit="return confirm('Отклонить черновик?');">
      <input type=hidden name=slug value="{{ d.slug }}">
      <button class=no>🗑 Отклонить</button>
    </form>
  </div>
</div>
{% endfor %}

{% if queue %}
<div class=queue>
  <h3>⏳ Одобрено, ждёт слота ({{ queue|length }})</h3>
  {% for q in queue %}
  <div class="qrow {{ 'bad' if q.problem }}">
    <span>{{ q.slug }}</span>
    <span class=meta>
      {% if q.problem == 'expired' %}⚠️ одобрение просрочено — вернётся в черновики
      {% elif q.problem == 'modified' %}⚠️ текст правили после одобрения — одобрение снято
      {% elif q.problem %}⚠️ {{ q.problem }}
      {% else %}одобрено {{ q.approved_at }} · годно до {{ q.expires_at }}{% endif %}
    </span>
    <form method=post action="/unapprove"><input type=hidden name=slug value="{{ q.slug }}">
      <button class=mini>↩ вернуть в черновики</button></form>
  </div>
  {% endfor %}
</div>
{% endif %}
</div></body></html>"""


@app.route("/")
def index():
    return render_template_string(TEMPLATE, drafts=load_drafts(), queue=load_queue(),
                                  slots=next_slots(), msg=request.args.get("msg", ""))


@app.route("/approve", methods=["POST"])
def approve():
    """Человек сказал «да». Пост уезжает в очередь со снапшотом — выйдет в ближайший слот."""
    slug = request.form.get("slug", "")
    if not os.path.exists(os.path.join(DRAFTS, slug + ".json")):
        return redirect(url_for("index", msg="Черновик не найден: " + slug))
    _move(slug, APPROVED)
    snap = S.write_approval(slug)
    R.audit("пульт: одобрено", "%s · годно до %s" % (slug, snap["expires_at"][:10]))
    nxt = next_slots(1)
    when = (" Ближайший слот: %s — %s." % (nxt[0]["when"], nxt[0]["rubric"])) if nxt else ""
    return redirect(url_for("index",
                            msg="✅ Одобрено и поставлено в очередь.%s Годно до %s." % (when, snap["expires_at"][:10])))


@app.route("/publish-now", methods=["POST"])
def publish_now():
    """Срочный выход мимо расписания — когда новость горит."""
    slug = request.form.get("slug", "")
    jpath = os.path.join(DRAFTS, slug + ".json")
    if not os.path.exists(jpath):
        return redirect(url_for("index", msg="Черновик не найден: " + slug))
    try:
        p = subprocess.run([sys.executable, PUBLISHER, jpath], cwd=HERE,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        out = (p.stdout or "") + " " + (p.stderr or "")
        m = re.search(r"message_id[:\s]+(\d+)", out)
        if p.returncode == 0 and m:
            _move(slug, PUBLISHED)
            R.audit("пульт: опубликовано вручную", "%s · message_id %s" % (slug, m.group(1)))
            return redirect(url_for("index", msg="✅ Опубликовано сейчас! message_id %s" % m.group(1)))
        return redirect(url_for("index", msg="Не опубликовалось (rc=%s): %s" % (p.returncode, out[-240:])))
    except Exception as e:
        return redirect(url_for("index", msg="Ошибка публикации: " + str(e)[:240]))


@app.route("/unapprove", methods=["POST"])
def unapprove():
    """Передумал: снять одобрение, вернуть в черновики."""
    slug = request.form.get("slug", "")
    ap = S.approval_path(slug)
    if os.path.exists(ap):
        try:
            os.remove(ap)
        except Exception:
            pass
    _move(slug, DRAFTS, src=APPROVED)
    R.audit("пульт: одобрение снято вручную", slug)
    return redirect(url_for("index", msg="↩ Одобрение снято, пост вернулся в черновики: " + slug))


@app.route("/reject", methods=["POST"])
def reject():
    slug = request.form.get("slug", "")
    _move(slug, REJECTED)
    R.audit("пульт: отклонено", slug)
    return redirect(url_for("index", msg="Черновик отклонён (в rejected/): " + slug))


def _open_browser():
    """Открыть пульт в браузере, когда сервер уже поднялся (владелец не набирает адрес руками)."""
    import threading, webbrowser
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5055")).start()


if __name__ == "__main__":
    print("Пульт апрува: http://127.0.0.1:5055   (закрыть — Ctrl+C в этом окне)")
    if "--no-browser" not in sys.argv:
        _open_browser()
    app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
