# -*- coding: utf-8 -*-
"""content_factory_run.py — оркестратор контент-завода (как study_run.py у Куратора).
Триггерится Windows-задачей ПО РАСПИСАНИЮ. На каждом прогоне:
  1) guard (STOP) + громкий статус «идёт»;
  2) drafting: диспатч субагента content-factory (headless claude -p) → ОДИН черновик в drafts/;
  3) громкий статус «готово/частично/ошибка» + история (ловит тихое падение).
НЕ публикует (человек-гейт). Публикация — рукой владельца после апрува.

Режим drafting: env CF_DRAFT_MODE = claude (по умолч.) | stub (быстрый тест ТОЛЬКО статуса/расписания).
"""
import os, sys, subprocess
# Windows-консоль по умолчанию cp1251/cp866 -> кириллица в print корёжится. Держим UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cf_rails as R

DRAFTS = os.path.join(HERE, "drafts")
MODE = os.environ.get("CF_DRAFT_MODE", "claude").strip()

# Полный путь к claude.exe: под Task Scheduler PATH может НЕ содержать ~/.local/bin.
# Порядок: env CF_CLAUDE_BIN -> известный путь -> голое "claude" (интерактив/PATH).
_CANDIDATE = os.path.expandvars(r"%USERPROFILE%\.local\bin\claude.exe")
CLAUDE_BIN = os.environ.get("CF_CLAUDE_BIN") or (_CANDIDATE if os.path.exists(_CANDIDATE) else "claude")

# Задача headless-прогону: агент content-factory ДЕЛАЕТ черновик САМ (инлайн, синхронно),
# НЕ спавнит фонового субагента. Иначе Task уходит в фон, one-shot `claude -p` выходит за ~50с
# и УБИВАЕТ субагента до записи файла -> пустой drafts/ при rc=0 (ложный успех). Ловлено на живом
# тесте шва 2026-07-16; фикс = запуск сессии КАК агента (--agent), работа в главном цикле.
TASK = (
    "Сделай ОДИН черновик поста для канала @pdn152fz_check по СВЕЖЕЙ повестке 152-ФЗ/РКН. "
    "Факты верифицируй до первоисточника. Положи JSON + ПРЕДПРОСМОТР в drafts/. "
    "НЕ публикуй. Верни путь к файлу черновика."
)


def run_drafting_claude():
    """headless: запускаем СЕССИЮ КАК агента content-factory (--agent) — он собирает черновик
    инлайн и синхронно (без фонового Task). Права: acceptEdits (Write) + весь набор агента в
    --allowedTools (в т.ч. WebFetch — первоисточники). Возвращает (ok, note)."""
    os.makedirs(DRAFTS, exist_ok=True)
    cmd = [
        CLAUDE_BIN, "-p", TASK,
        "--agent", "content-factory",
        "--permission-mode", "acceptEdits",
        "--allowedTools", "Read", "Grep", "Glob", "Bash", "Write", "WebSearch", "WebFetch",
    ]
    try:
        # claude шлёт UTF-8; НЕ отдавать декод дефолтному cp1251 (иначе поток-читатель падает
        # UnicodeDecodeError -> note теряется + шумный трейсбек). Явный utf-8 + replace.
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1200)
        out = (p.stdout or "").replace("\n", " ")
        if p.returncode == 0:
            return True, "claude --agent ok: " + out[-160:]
        return False, "claude --agent rc=%d: %s" % (p.returncode, ((p.stderr or out)[-160:]))
    except FileNotFoundError:
        return False, "claude CLI не найден (%s) — headless-диспатч недоступен" % CLAUDE_BIN
    except subprocess.TimeoutExpired:
        return False, "claude --agent таймаут (1200с)"
    except Exception as e:
        return False, "claude --agent сбой: %s" % str(e)[:160]


def run_drafting_stub():
    """Быстрый тест: пишет draft-REQUEST (не пост!), чтобы проверить статус/расписание без LLM."""
    os.makedirs(DRAFTS, exist_ok=True)
    stamp = R._now().replace(":", "-").replace(" ", "_")
    req = os.path.join(DRAFTS, "_DRAFT_REQUEST_%s.txt" % stamp)
    with open(req, "w", encoding="utf-8") as f:
        f.write("Запрос черновика от планировщика %s (режим stub — проверка расписания/статуса).\n"
                "Реальный черновик делает субагент content-factory.\n" % R._now())
    return True, "stub: записан draft-request (проверка расписания, без LLM)"


def _draft_files():
    """Реальные файлы черновиков в drafts/ (без служебных _DRAFT_REQUEST_* и прочих _*)."""
    try:
        return {f for f in os.listdir(DRAFTS)
                if not f.startswith("_") and (f.endswith(".json") or f.endswith(".md"))}
    except FileNotFoundError:
        return set()


def main():
    R.guard("content-factory")
    rec = R.status_start("content-factory")
    steps = {}
    before = _draft_files()
    try:
        if MODE == "stub":
            ok, note = run_drafting_stub()
            steps["режим"] = "stub"
            steps["черновик"] = "ok (stub-заявка)" if ok else "не собран"
            verdict = "готово" if ok else "частично"
        else:
            ok, note = run_drafting_claude()
            steps["режим"] = "claude --agent"
            # Fix C: правда = реально появившийся НОВЫЙ .json-черновик, НЕ rc=0.
            # Ловит ложный успех (rc=0 при пустой очереди — напр. фоновый субагент умер).
            new = sorted(_draft_files() - before)
            new_json = [f for f in new if f.endswith(".json")]
            if new_json:
                steps["черновик"] = "ok: " + ", ".join(new_json)
                note = "новый черновик: " + ", ".join(new_json)
                verdict = "готово"
            else:
                steps["черновик"] = "НЕ СОБРАН (rc=%s, но нового файла в drafts/ нет)" % ("0" if ok else "!=0")
                verdict = "частично"
    except Exception as e:
        verdict, note = "ошибка", str(e)[:200]
        steps["черновик"] = "сбой"
    R.status_end(rec, verdict, steps, note)
    print("[content-factory] %s — %s" % (verdict, note))


if __name__ == "__main__":
    main()
