# -*- coding: utf-8 -*-
"""approve_console.py — локальный ПУЛЬТ АПРУВА черновиков контент-завода.
Человек-гейт кликом: видишь черновик -> жмёшь «Одобрить и опубликовать» -> публикуется
через publisher/publish_telegram.py (секреты берёт он сам из .env проекта, пульт их не трогает).
Публикует ТОЛЬКО по клику и ТОЛЬКО в Telegram (VK — вручную, нет аккаунта).
Локально: http://127.0.0.1:5055 . Остановить — Ctrl+C в окне.
"""
import os, sys, glob, json, base64, subprocess, shutil, re
from flask import Flask, request, redirect, render_template_string, url_for

HERE = os.path.dirname(os.path.abspath(__file__))
DRAFTS = os.path.join(HERE, "drafts")
PUBLISHED = os.path.join(HERE, "published")
REJECTED = os.path.join(HERE, "rejected")
PUBLISHER = os.path.join(HERE, "publisher", "publish_telegram.py")

app = Flask(__name__)


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


def _move(slug, dest):
    os.makedirs(dest, exist_ok=True)
    pats = glob.glob(os.path.join(DRAFTS, slug + ".*")) + glob.glob(os.path.join(DRAFTS, "*" + slug + ".*"))
    for p in set(pats):
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
 .no{background:#2a2f3a;color:#cbd2dc} .no:hover{background:#3a4150}
 .empty{color:#8b93a0;text-align:center;padding:50px 0}
 a{color:#6cb6ff}
 .gate{font-size:12px;color:#ffce7a;margin:0 18px 6px}
</style></head><body><div class=wrap>
<h1>🏭 Пульт апрува · @pdn152fz_check</h1>
<div class=sub>Черновики от контент-завода. Публикует <b>только по твоему клику</b>, только Telegram. VK — скопируй вручную.</div>
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
  <div class=gate>Нажимая «Одобрить», ты публикуешь в БОЕВОЙ канал. Проверь факты и картинку.</div>
  <div class=actions>
    <form method=post action="/approve" onsubmit="return confirm('Опубликовать в @pdn152fz_check? Это боевой канал.');">
      <input type=hidden name=slug value="{{ d.slug }}">
      <button class=ok>✅ Одобрить и опубликовать в Telegram</button>
    </form>
    <form method=post action="/reject" onsubmit="return confirm('Отклонить черновик?');">
      <input type=hidden name=slug value="{{ d.slug }}">
      <button class=no>🗑 Отклонить</button>
    </form>
  </div>
</div>
{% endfor %}
</div></body></html>"""


@app.route("/")
def index():
    return render_template_string(TEMPLATE, drafts=load_drafts(), msg=request.args.get("msg", ""))


@app.route("/approve", methods=["POST"])
def approve():
    slug = request.form.get("slug", "")
    jpath = os.path.join(DRAFTS, slug + ".json")
    if not os.path.exists(jpath):
        return redirect(url_for("index", msg="Черновик не найден: " + slug))
    try:
        p = subprocess.run([sys.executable, PUBLISHER, jpath], cwd=HERE,
                           capture_output=True, text=True, timeout=90)
        out = (p.stdout or "") + " " + (p.stderr or "")
        m = re.search(r"message_id[:\s]+(\d+)", out)
        if p.returncode == 0 and m:
            _move(slug, PUBLISHED)
            return redirect(url_for("index", msg="✅ Опубликовано! message_id %s — черновик убран из очереди." % m.group(1)))
        return redirect(url_for("index", msg="Не опубликовалось (rc=%s): %s" % (p.returncode, out[-240:])))
    except Exception as e:
        return redirect(url_for("index", msg="Ошибка публикации: " + str(e)[:240]))


@app.route("/reject", methods=["POST"])
def reject():
    slug = request.form.get("slug", "")
    _move(slug, REJECTED)
    return redirect(url_for("index", msg="Черновик отклонён (в rejected/): " + slug))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)
