# -*- coding: utf-8 -*-
"""
Публикатор в Telegram-канал (по умолчанию @pdn152fz_check) через бота канала.

Токен НЕ хранится в коде: скрипт берёт его в момент запуска из секрет-брокера
(env CF_VAULT, опционально) или из .env в корне проекта (TELEGRAM_BOT_TOKEN /
TELEGRAM_CHANNEL). Значение токена никогда не печатается.

Запуск:  python publisher/publish_telegram.py <путь_к_json>
JSON — от скилла pdn-content-factory (берём platforms.telegram.content, image_file/image_url).
"""
import json, os, sys, uuid, subprocess, urllib.request, urllib.parse

# Источники токена (по порядку): опциональный секрет-брокер (env CF_VAULT = путь к
# PowerShell-скрипту с командой `get <id>`, напр. DPAPI-сейф) -> .env в корне проекта.
# Значение нигде не печатается; строка [secret] в stderr показывает только ИСТОЧНИК.
VAULT = os.environ.get("CF_VAULT", "")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_vault(secret_id, env_name):
    """Достаёт ключ из брокера (CF_VAULT). Значение живёт только в этом процессе."""
    if not VAULT or not os.path.exists(VAULT):
        return False
    for exe in ("pwsh", r"C:\Program Files\PowerShell\7\pwsh.exe"):
        try:
            r = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-File", VAULT, "get", secret_id],
                               capture_output=True, text=True, timeout=25)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if r.returncode == 0 and r.stdout.strip():
            os.environ.setdefault(env_name, r.stdout.strip())
            return True
        return False
    return False


def load_env(path):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def api(method, params):
    url = "https://api.telegram.org/bot" + TOKEN + "/" + method
    data = urllib.parse.urlencode(params).encode("utf-8")
    with urllib.request.urlopen(url, data=data, timeout=20) as r:
        return json.load(r)


def api_photo_file(method, fields, file_path):
    """multipart/form-data: шлём ЛОКАЛЬНЫЙ файл (photo) + текстовые поля (chat_id, caption)."""
    url = "https://api.telegram.org/bot" + TOKEN + "/" + method
    boundary = "----pdn" + uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += ("--" + boundary + "\r\n").encode()
        body += ('Content-Disposition: form-data; name="%s"\r\n\r\n' % k).encode()
        body += (str(v) + "\r\n").encode("utf-8")
    with open(file_path, "rb") as f:
        blob = f.read()
    body += ("--" + boundary + "\r\n").encode()
    body += ('Content-Disposition: form-data; name="photo"; filename="%s"\r\n'
             % os.path.basename(file_path)).encode()
    body += b"Content-Type: image/png\r\n\r\n"
    body += blob + b"\r\n"
    body += ("--" + boundary + "--\r\n").encode()
    req = urllib.request.Request(
        url, data=bytes(body),
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


FROM_VAULT = load_vault("pdn152fz.bot_token", "TELEGRAM_BOT_TOKEN")  # сперва брокер (если задан)
load_env(os.path.join(ROOT, ".env"))     # штатный путь: .env в корне проекта (см. .env.example)
load_env(os.path.join(HERE, ".env"))     # локальный .env рядом со скриптом — переопределение

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@pdn152fz_check").strip()

print("[secret] TELEGRAM_BOT_TOKEN: %s" % ("vault" if FROM_VAULT else ".env (fallback)"),
      file=sys.stderr)

if not TOKEN or "ВСТАВЬ" in TOKEN:
    sys.exit("Нет TELEGRAM_BOT_TOKEN — заполни .env в корне проекта (шаблон: .env.example).")
if len(sys.argv) < 2:
    sys.exit("Укажи JSON-пост:  python publish_telegram.py <путь_к_json>")

post = json.load(open(sys.argv[1], encoding="utf-8"))
text = post["platforms"]["telegram"]["content"]
img = post.get("image_url")
imgfile = post.get("image_file")
has_file = bool(imgfile) and os.path.exists(str(imgfile))
has_url = bool(img) and str(img).startswith("http")

if has_file:                              # локальная картинка (gpt-image-1 → PNG) — приоритет
    if len(text) <= 1024:                 # лимит подписи под фото
        res = api_photo_file("sendPhoto", {"chat_id": CHANNEL, "caption": text}, imgfile)
    else:
        api_photo_file("sendPhoto", {"chat_id": CHANNEL}, imgfile)
        res = api("sendMessage", {"chat_id": CHANNEL, "text": text, "disable_web_page_preview": "true"})
elif has_url:                             # картинка по HTTP-URL (dall-e-3 и т.п.)
    if len(text) <= 1024:
        res = api("sendPhoto", {"chat_id": CHANNEL, "photo": img, "caption": text})
    else:
        api("sendPhoto", {"chat_id": CHANNEL, "photo": img})
        res = api("sendMessage", {"chat_id": CHANNEL, "text": text, "disable_web_page_preview": "true"})
else:                                     # только текст
    res = api("sendMessage", {"chat_id": CHANNEL, "text": text, "disable_web_page_preview": "true"})

if res.get("ok"):
    print("OK — опубликовано в", CHANNEL, "| message_id:", res["result"].get("message_id"))
else:
    print("Ошибка Telegram:", json.dumps(res, ensure_ascii=False))
    print("Если 'not enough rights' / 'chat not found' — сделай @pdn_compliance_bot админом канала.")
    sys.exit(1)
