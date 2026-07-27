# -*- coding: utf-8 -*-
"""cf_env.py — единая загрузка машинно-локальных настроек из .env в корне проекта.

Зачем отдельный модуль: пути и секреты нельзя держать в .bat-файлах. Консоль Windows
читает .bat в OEM-кодировке, и любой кириллический путь (а он у нас есть — репозиторий
лендинга) превращается в мусор и рвёт файл на части. Проверено на живом сбое 2026-07-27.
Поэтому: .bat остаются ASCII-only и ничего не знают о настройках, а .env лежит в UTF-8,
вне git, и читается отсюда.

Импортировать ПЕРВЫМ, до чтения os.environ:  import cf_env  # noqa
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def load(path=None):
    """KEY=VALUE построчно. Уже заданное в окружении не перетираем (env сильнее файла)."""
    path = path or os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
        return True
    except Exception:
        return False


load()
