# LLM Bench

Независимый агрегатор бенчмарков открытых языковых моделей.

**[llm-bench.ru](https://llm-bench.ru)** — отслеживаем и сравниваем LLM по ключевым метрикам.

## Что это

LLM Bench автоматически собирает данные из открытых источников и формирует единый лидерборд моделей:

- **Artificial Analysis** — Intelligence Index (агрегированная метрика: MMLU-Pro, GPQA, HLE, IFBench, SciCode, LiveCodeBench и др.), скорость генерации, цена, лицензия
- **TIGER-Lab MMLU-Pro** — 12K вопросов по 14 областям знаний (как дополнительная метрика)
- **Arena AI** — рейтинг на основе слепых попарных сравнений пользователями (отдельный блок, 7 категорий)

Основной рейтинг строится на Intelligence Index от Artificial Analysis. Остальные источники показываются как дополнительные срезы.

## Как работает

```
[cron: ежедневно] → update.py → fetch APIs → render template → index.html
```

Скрипт `update.py` забирает данные из публичных API без аутентификации, объединяет результаты из нескольких источников и генерирует статический HTML.

## Источники данных

| Источник | Что даёт | URL |
|----------|----------|-----|
| Artificial Analysis | Intelligence Index, скорость, цена, лицензия | [artificialanalysis.ai](https://artificialanalysis.ai/leaderboards/models) |
| TIGER-Lab MMLU-Pro | Скоры по 14 предметам (доп. колонка) | [HF Dataset](https://huggingface.co/datasets/TIGER-Lab/mmlu_pro_leaderboard_submission) |
| Arena AI | ELO рейтинги по 7 категориям | [arena.ai](https://arena.ai) |

## Запуск

```bash
# Установить зависимости (нет — только stdlib Python 3.10+)

# Разовый запуск
python3 update.py

# Или с кастомными путями
LLM_BENCH_TEMPLATE=template.html \
LLM_BENCH_OUTPUT=dist/index.html \
LLM_BENCH_CACHE=cache.json \
python3 update.py

# Cron (ежедневно в 6:00 MSK)
0 3 * * * /usr/bin/python3 /path/to/update.py >> /var/log/llm-bench.log 2>&1
```

## Структура

```
├── update.py          # Скрипт генерации
├── template.html      # HTML-шаблон
├── cache.json         # Кеш последнего запуска (автоматически)
├── dist/
│   └── index.html     # Сгенерированный сайт
├── fonts/             # Geist + Geist Mono (woff2)
└── README.md
```

## Лицензия

MIT
