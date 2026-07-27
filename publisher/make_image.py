# -*- coding: utf-8 -*-
"""
Генератор картинки к посту через OpenAI Image API (по умолчанию gpt-image-1).

Берёт image_prompt из JSON поста (от скилла pdn-content-factory), генерит картинку,
сохраняет PNG рядом с JSON и вписывает путь в поле image_file того же JSON.
Публикатор publish_telegram.py потом сам подхватит image_file и отправит фото.

Ключ OpenAI НЕ хранится в коде: скрипт берёт его в момент запуска из секрет-брокера
(env CF_VAULT, опционально; id = openai.api_key) или из .env в корне проекта.
Значение ключа нигде не печатается; строка [secret] в stderr показывает только
ИСТОЧНИК (vault / .env).

Запуск:  python publisher/make_image.py <путь_к_json>
Модель:  переопределяется переменной OPENAI_IMAGE_MODEL (по умолчанию gpt-image-1).
Размер:  переопределяется OPENAI_IMAGE_SIZE (по умолчанию 1024x1024).
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

# Источники ключа (по порядку): опциональный секрет-брокер (env CF_VAULT) -> .env проекта.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import cf_env  # noqa: F401  — .env проекта -> окружение (в т.ч. CF_VAULT)

VAULT = os.environ.get("CF_VAULT", "")


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


def die(msg):
    sys.exit(msg)


FROM_VAULT = load_vault("openai.api_key", "OPENAI_API_KEY")  # сперва брокер (если задан)
load_env(os.path.join(ROOT, ".env"))     # штатный путь: .env в корне проекта (см. .env.example)
load_env(os.path.join(HERE, ".env"))     # локальный .env рядом со скриптом — переопределение

print("[secret] OPENAI_API_KEY: %s" % ("vault" if FROM_VAULT else ".env (fallback)"),
      file=sys.stderr)

KEY = os.environ.get("OPENAI_API_KEY", "").strip()
MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1").strip()
SIZE = os.environ.get("OPENAI_IMAGE_SIZE", "1536x1024").strip()      # альбомный — фото-лента смотрится лучше
QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "high").strip()     # high = фотокачество (дороже)

if not KEY or "ВСТАВЬ" in KEY:
    die("Нет OPENAI_API_KEY — заполни .env в корне проекта (шаблон: .env.example). "
        "Ключ вписывает владелец своей рукой — модель его не видит.")
if len(sys.argv) < 2:
    die("Укажи JSON-пост:  python make_image.py <путь_к_json>")

json_path = sys.argv[1]
post = json.load(open(json_path, encoding="utf-8"))
prompt = (post.get("image_prompt") or "").strip()
if not prompt:
    die("В JSON нет image_prompt — нечего рисовать.")

body = json.dumps({
    "model": MODEL,
    "prompt": prompt,
    "n": 1,
    "size": SIZE,
    "quality": QUALITY,
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.openai.com/v1/images/generations",
    data=body,
    headers={
        "Authorization": "Bearer " + KEY,
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.load(r)
except urllib.error.HTTPError as e:
    detail = e.read().decode("utf-8", "replace")[:400]
    die("OpenAI ошибка {}: {}".format(e.code, detail))
except Exception as e:  # noqa
    die("Сбой запроса к OpenAI: {}".format(e))

data = (resp.get("data") or [{}])[0]

# gpt-image-1 отдаёт b64_json; dall-e-3 может отдать url — поддержим оба.
out_png = os.path.splitext(json_path)[0] + ".png"
if data.get("b64_json"):
    with open(out_png, "wb") as f:
        f.write(base64.b64decode(data["b64_json"]))
    post["image_file"] = out_png
    post["image_url"] = None
    print("OK — картинка сохранена:", out_png)
elif data.get("url"):
    post["image_url"] = data["url"]
    post["image_file"] = None
    print("OK — картинка по URL:", data["url"])
else:
    die("OpenAI вернул ответ без b64_json/url: " + json.dumps(resp, ensure_ascii=False)[:300])

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(post, f, ensure_ascii=False, indent=2)
print("JSON обновлён:", json_path)
