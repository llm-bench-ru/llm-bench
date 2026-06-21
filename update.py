#!/usr/bin/env python3
"""
LLM Bench — open-source LLM leaderboard generator.
Primary source: Artificial Analysis (intelligenceIndex).
Supplementary: TIGER-Lab MMLU-Pro, Arena AI (per-category tabs).
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

# ─── Config (override via env vars) ───────────────────────────────────────

TEMPLATE = os.environ.get("LLM_BENCH_TEMPLATE", "template.html")
OUTPUT = os.environ.get("LLM_BENCH_OUTPUT", "dist/index.html")
CACHE = os.environ.get("LLM_BENCH_CACHE", "cache.json")
MSK = timezone(timedelta(hours=3))
CACHE_MAX_AGE_DAYS = 7

LEADERBOARD_LIMIT = None  # show all AA models
PAGE_SIZE = 20
RELEASES_LIMIT = 8

# Artificial Analysis (primary source — intelligenceIndex, speed, price, license)
AA_URL = "https://artificialanalysis.ai/leaderboards/models?weights=open%2Cproprietary"

# TIGER-Lab MMLU-Pro Leaderboard (supplementary academic benchmark)
MMLU_PRO_URLS = [
    "https://datasets-server.huggingface.co/rows?dataset=TIGER-Lab%2Fmmlu_pro_leaderboard_submission&config=default&split=train&offset=0&limit=100",
    "https://datasets-server.huggingface.co/rows?dataset=TIGER-Lab%2Fmmlu_pro_leaderboard_submission&config=default&split=train&offset=100&limit=100",
    "https://datasets-server.huggingface.co/rows?dataset=TIGER-Lab%2Fmmlu_pro_leaderboard_submission&config=default&split=train&offset=200&limit=100",
]

# Arena AI per-category tabs (separate section)
ARENA_PAGES = {
    "text":           "https://arena.ai/leaderboard/text/overall",
    "code":           "https://arena.ai/leaderboard/text/coding",
    "vision":         "https://arena.ai/leaderboard/vision",
    "text-to-image":  "https://arena.ai/leaderboard/text-to-image",
    "image-edit":     "https://arena.ai/leaderboard/image-edit",
    "text-to-video":  "https://arena.ai/leaderboard/text-to-video",
    "search":         "https://arena.ai/leaderboard/search",
}
ARENA_CATEGORIES = list(ARENA_PAGES.keys())
ARENA_CATEGORY_NAMES = {
    "text": "Общий",
    "code": "Код",
    "vision": "Зрение",
    "text-to-image": "Генерация изображений",
    "image-edit": "Редактирование изображений",
    "text-to-video": "Генерация видео",
    "search": "Поиск",
}
OPEN_LICENSES = {
    "apache 2.0", "mit", "modified mit", "gemma", "gemma license",
    "llama 3.1", "llama 3.2", "llama 3.3", "llama 4",
    "cc-by-4.0", "cc-by-sa-4.0", "cc-by-nc-4.0", "bsd-3-clause",
    "deepseek", "qwen", "yi", "gpl-3.0", "agpl-3.0",
}


# ─── Helpers ───────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S MSK")
    print(f"[{ts}] {msg}", flush=True)


def fetch_json(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "llm-bench-updater/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log(f"WARN: Failed to fetch {url}: {e}")
        return None


def fetch_html(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except Exception as e:
        log(f"WARN: Failed to fetch {url}: {e}")
        return None


def safe(text):
    return escape(str(text)) if text else ""


def _float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _normalize(name):
    return name.lower().replace("-", "").replace("_", "").replace(" ", "").replace("(", "").replace(")", "")


def _fuzzy_match(key, candidate):
    if len(key) < 6 or len(candidate) < 6:
        return False
    if key in candidate or candidate in key:
        shorter, longer = (key, candidate) if len(key) < len(candidate) else (candidate, key)
        return len(shorter) >= len(longer) * 0.6
    return False


def row_class(rank):
    if rank == 1:
        return ' class="row-gold"'
    if rank == 2:
        return ' class="row-silver"'
    if rank == 3:
        return ' class="row-bronze"'
    return ""


def format_date_ru(dt_str):
    months = {1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
              7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек"}
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return f"{dt.day} {months.get(dt.month, '???')} {dt.year}"
    except Exception:
        return ""


def _is_open_license(license_str):
    if not license_str:
        return False
    ls = license_str.lower().strip()
    if ls == "proprietary":
        return False
    for ol in OPEN_LICENSES:
        if ol in ls:
            return True
    return ls != ""


# ─── Score formatting & bar widths ─────────────────────────────────────────

def fmt_intel(val):
    """Intelligence Index (0-100 scale, AA blended)."""
    if val is None:
        return "—"
    return f"{val:.1f}"


def intel_class(val):
    if val is None:
        return ""
    if val >= 50:
        return "score-top"
    if val >= 35:
        return "score-mid"
    return ""


def intel_bar_pct(val):
    if val is None:
        return 0
    return max(0, min(100, val * 1.4))  # 0..70 → 0..98%


def fmt_score(val):
    if val is None:
        return "—"
    return f"{val:.1f}"


def score_class(val):
    if val is None:
        return ""
    if val >= 80:
        return "score-top"
    if val >= 65:
        return "score-mid"
    return ""


def fmt_speed(v):
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.1f}k"
    return f"{int(round(v))}"


def fmt_ttft(v):
    if v is None:
        return "—"
    if v >= 10:
        return f"{v:.0f}с"
    return f"{v:.1f}с"


def fmt_price(v):
    if v is None:
        return "—"
    if v == 0:
        return "free"
    if v < 0.1:
        return f"${v:.3f}"
    if v < 1:
        return f"${v:.2f}"
    return f"${v:.1f}"


def fmt_count(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)


# ─── Artificial Analysis (primary) ─────────────────────────────────────────

def _extract_aa_models(html):
    """Extract model objects from AA Next.js RSC payload."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
    if not chunks:
        return []
    big = max(chunks, key=len)
    try:
        big = big.encode().decode('unicode_escape')
    except UnicodeDecodeError:
        return []

    models = []
    pat = re.compile(r'\{"id":"[a-f0-9-]{36}","name":"')
    for m in pat.finditer(big):
        start = m.start()
        depth = 0
        in_str = False
        esc = False
        end = start
        for j in range(start, min(start + 30000, len(big))):
            c = big[j]
            if esc:
                esc = False
                continue
            if c == '\\':
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        raw = big[start:end].replace('"$undefined"', 'null')
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if 'intelligenceIndex' in obj:
            models.append(obj)
    return models


def fetch_artificial_analysis():
    """Scrape Artificial Analysis leaderboard."""
    log("Fetching Artificial Analysis leaderboard...")
    html = fetch_html(AA_URL, timeout=30)
    if not html:
        return None
    raw = _extract_aa_models(html)
    if not raw:
        log("  WARN: no AA models extracted")
        return None

    out = []
    seen = set()
    for r in raw:
        name = (r.get("name") or "").strip()
        if not name or r.get("deprecated"):
            continue
        key = _normalize(name)
        if key in seen:
            continue
        seen.add(key)

        intel = _float(r.get("intelligenceIndex"))
        if intel is None:
            continue

        license_name = r.get("licenseName") or ""
        is_open = bool(r.get("isOpenWeights"))
        commercial_ok = r.get("commercialAllowed")

        clean_name, effort_label = _split_effort_suffix(name)
        out.append({
            "name": clean_name,
            "effort": effort_label,
            "creator": r.get("modelCreatorName") or "",
            "creator_logo": r.get("modelCreatorLogo") or "",
            "release_date": r.get("releaseDate") or "",
            "reasoning": bool(r.get("reasoningModel")),
            "intel": round(intel, 1),
            "intel_estimated": bool(r.get("intelligenceIndexIsEstimated")),
            "coding": _round1(r.get("codingIndex")),
            "agentic": _round1(r.get("agenticIndex")),
            "mmmu_pro": _round1(r.get("mmmuPro")),
            "gpqa": _round1(r.get("gpqa")),
            "hle": _round1(r.get("hle")),
            "ifbench": _round1(r.get("ifbench")),
            "scicode": _round1(r.get("scicode")),
            "speed": _float(r.get("medianOutputTokensPerSecond")),
            "ttft": _float(r.get("medianTimeToFirstTokenSeconds")),
            "price_in": _float(r.get("price1mInputTokens")),
            "price_out": _float(r.get("price1mOutputTokens")),
            "is_open": is_open,
            "commercial_allowed": commercial_ok,
            "license_name": license_name,
            "license_url": r.get("licenseUrl") or "",
            "hf_url": r.get("huggingfaceUrl") or "",
            "mmlu_pro": None,  # filled by merge_mmlu_into_aa
        })

    out.sort(key=lambda m: m["intel"], reverse=True)
    log(f"  AA: {len(out)} models (sorted by intelligenceIndex)")
    return out


def _round1(v):
    f = _float(v)
    return round(f, 2) if f is not None else None


def _split_effort_suffix(name):
    """Strip trailing '(...)' from model name, return (clean_name, effort_label)."""
    m = re.search(r'\s*\(([^()]+)\)\s*$', name)
    if not m:
        return name, ""
    inner = m.group(1).strip()
    clean = name[:m.start()].rstrip()
    low = inner.lower()
    # Bare "reasoning" — already covered by reasoning badge, drop suffix
    if low in ("reasoning", "thinking", "non-reasoning", "non reasoning"):
        return clean, ""
    if "max effort" in low or "xhigh" in low or low == "max":
        label = "MAX"
    elif "high" in low and "adaptive" not in low:
        label = "HIGH"
    elif "medium" in low or low == "med":
        label = "MED"
    elif "minimal" in low or "low" in low:
        label = "LOW"
    elif "adaptive" in low:
        label = "ADAPTIVE"
    else:
        label = inner[:14].upper()
    return clean, label


# ─── MMLU-Pro (supplementary) ──────────────────────────────────────────────

def fetch_mmlu_pro():
    log("Fetching MMLU-Pro leaderboard...")
    all_rows = []
    for url in MMLU_PRO_URLS:
        data = fetch_json(url, timeout=20)
        if data and "rows" in data:
            all_rows.extend(data["rows"])
    if not all_rows:
        return None

    models = []
    seen = set()
    for row in all_rows:
        r = row.get("row", {})
        name = r.get("Models", "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        overall = _float(r.get("Overall"))
        if overall is None or overall < 0.1:
            continue
        models.append({
            "name": name,
            "overall": round(overall * 100, 1),
        })
    log(f"  MMLU-Pro: {len(models)} entries")
    return models


def merge_mmlu_into_aa(aa_models, mmlu_models):
    if not mmlu_models:
        return
    mmlu_norm = {_normalize(m["name"]): m for m in mmlu_models}
    matched = 0
    for am in aa_models:
        key = _normalize(am["name"])
        mm = mmlu_norm.get(key)
        if not mm:
            for mkey, mval in mmlu_norm.items():
                if _fuzzy_match(key, mkey):
                    mm = mval
                    break
        if not mm and len(key) >= 5:
            for mkey, mval in mmlu_norm.items():
                if key in mkey or mkey in key:
                    mm = mval
                    break
        if mm:
            am["mmlu_pro"] = mm["overall"]
            matched += 1
    log(f"  Merged MMLU-Pro into {matched}/{len(aa_models)} AA models")


# ─── Arena AI (per-category tabs) ──────────────────────────────────────────

def _extract_arena_entries(html):
    idx = html.find('entries\\":[{')
    if idx < 0:
        idx = html.find('"entries":[{')
        if idx < 0:
            return None
    start = html.find('[{', idx)
    if start < 0:
        return None
    bracket_count = 0
    end = start
    for i in range(start, min(start + 1000000, len(html))):
        if html[i] == '[' and (i == 0 or html[i-1] != '\\'):
            bracket_count += 1
        elif html[i] == ']' and (i == 0 or html[i-1] != '\\'):
            bracket_count -= 1
            if bracket_count == 0:
                end = i + 1
                break
    raw = html[start:end].replace('\\"', '"').replace('\\\\', '\\')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def fetch_arena_categories():
    log("Fetching Arena AI per-category leaderboards...")
    results = {}
    results_open = {}
    for cat, url in ARENA_PAGES.items():
        html = fetch_html(url, timeout=20)
        if not html:
            continue
        entries = _extract_arena_entries(html)
        if not entries:
            log(f"  WARN: No entries for arena/{cat}")
            continue
        all_models = []
        open_models = []
        for e in entries:
            score = e.get("rating")
            if not score:
                continue
            ci = None
            upper = e.get("ratingUpper")
            lower = e.get("ratingLower")
            if upper and lower:
                ci = round((upper - lower) / 2)
            license_str = e.get("license", "")
            is_open = _is_open_license(license_str)
            entry = {
                "rank": e.get("rank", 0),
                "model": e.get("modelDisplayName", "").strip(),
                "vendor": e.get("modelOrganization", ""),
                "license": "open" if is_open else "proprietary",
                "license_name": license_str,
                "score": round(score),
                "ci": ci,
                "votes": e.get("votes", 0),
            }
            all_models.append(entry)
            if is_open:
                open_models.append(entry)
        all_models.sort(key=lambda x: x["score"], reverse=True)
        open_models.sort(key=lambda x: x["score"], reverse=True)
        results[cat] = all_models
        results_open[cat] = open_models
        log(f"  Arena/{cat}: {len(all_models)} total, {len(open_models)} open")
    return results, results_open


# ─── Render ────────────────────────────────────────────────────────────────

LICENSE_BADGE_OPEN = ' <span style="font-size:0.5625rem;font-weight:700;font-family:var(--font-mono);padding:1px 4px;border-radius:3px;background:hsl(160 84% 45% / 0.15);color:hsl(160 84% 45%);vertical-align:middle;letter-spacing:0.03em">OSS</span>'
LICENSE_BADGE_PROP = ' <span style="font-size:0.5625rem;font-weight:700;font-family:var(--font-mono);padding:1px 4px;border-radius:3px;background:hsl(0 0% 50% / 0.1);color:hsl(0 0% 40%);vertical-align:middle;letter-spacing:0.03em">Proprietary</span>'
REASONING_BADGE = ' <span style="font-size:0.5625rem;font-weight:700;font-family:var(--font-mono);padding:1px 4px;border-radius:3px;background:hsl(280 60% 55% / 0.15);color:hsl(280 60% 65%);vertical-align:middle;letter-spacing:0.03em">REASONING</span>'

EFFORT_COLORS = {
    "MAX":      ("hsl(0 70% 55% / 0.18)",   "hsl(0 70% 65%)"),
    "HIGH":     ("hsl(20 80% 55% / 0.18)",  "hsl(20 80% 65%)"),
    "MED":      ("hsl(45 80% 55% / 0.18)",  "hsl(45 80% 65%)"),
    "LOW":      ("hsl(210 30% 55% / 0.15)", "hsl(210 30% 65%)"),
    "ADAPTIVE": ("hsl(160 60% 50% / 0.15)", "hsl(160 60% 60%)"),
}


def effort_badge(label):
    if not label:
        return ""
    bg, fg = EFFORT_COLORS.get(label, ("hsl(0 0% 35% / 0.2)", "hsl(0 0% 65%)"))
    return f' <span style="font-size:0.5625rem;font-weight:700;font-family:var(--font-mono);padding:1px 4px;border-radius:3px;background:{bg};color:{fg};vertical-align:middle;letter-spacing:0.03em">{safe(label)}</span>'


def render_leaderboard_rows(models):
    rows = []
    for i, m in enumerate(models, 1):
        is_open = m.get("is_open")
        license_badge = LICENSE_BADGE_OPEN if is_open else LICENSE_BADGE_PROP
        reasoning_badge = REASONING_BADGE if m.get("reasoning") else ""
        data_license = ' data-license="open"' if is_open else ' data-license="proprietary"'

        intel = m.get("intel")
        coding = m.get("coding")
        mmlu = m.get("mmlu_pro")
        speed = m.get("speed")
        ttft = m.get("ttft")
        price_out = m.get("price_out")

        bar_pct = intel_bar_pct(intel)
        bar_cls = "bar-top" if intel and intel >= 50 else ("bar-mid" if intel and intel >= 35 else "")

        license_name = safe(m.get("license_name") or ("Open" if is_open else "Proprietary"))
        license_url = m.get("license_url") or ""
        license_html = f'<a href="{safe(license_url)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline;text-underline-offset:2px">{license_name}</a>' if license_url else license_name

        hf_url = m.get("hf_url") or ""
        hf_html = f'<a href="{safe(hf_url)}" target="_blank" rel="noopener" style="color:hsl(40 95% 55%);text-decoration:none">🤗</a>' if hf_url else ""

        rows.append(f"""                <tr{row_class(i)}{data_license}>
                  <td class="rank">{i}</td>
                  <td class="model-name">
                    <span style="font-weight:600">{safe(m['name'])}</span>{effort_badge(m.get('effort', ''))}{license_badge}{reasoning_badge}<br /><span class="model-author">{safe(m.get('creator', ''))} {hf_html}</span>
                  </td>
                  <td class="num {intel_class(intel)}">{fmt_intel(intel)}</td>
                  <td class="num {score_class(coding)}">{fmt_score(coding)}</td>
                  <td class="num">{fmt_speed(speed)}</td>
                  <td class="num">{fmt_ttft(ttft)}</td>
                  <td class="num">{fmt_price(price_out)}</td>
                  <td class="num" style="font-size:0.6875rem">{license_html}</td>
                  <td class="bar-cell">
                    <div class="bar-track {bar_cls}"><div class="bar-fill" style="width: {bar_pct:.1f}%"></div></div>
                  </td>
                </tr>""")
    return "\n".join(rows)


def render_aa_card(m):
    name = m["name"]
    effort = m.get("effort", "")
    creator = m.get("creator", "")
    intel = m.get("intel")
    is_open = m.get("is_open")
    badge = "OSS" if is_open else "Proprietary"
    badge_color = "hsl(160 84% 45%)" if is_open else "hsl(0 0% 40%)"
    badge_bg = "hsl(160 84% 45% / 0.15)" if is_open else "hsl(0 0% 50% / 0.1)"

    release = format_date_ru(m.get("release_date", ""))
    intel_str = fmt_intel(intel)
    speed = m.get("speed")
    price = m.get("price_out")

    meta_bits = []
    if release:
        meta_bits.append(release)
    if speed is not None:
        meta_bits.append(f"{fmt_speed(speed)} t/s")
    if price is not None:
        meta_bits.append(fmt_price(price) + "/1M")
    meta = " · ".join(meta_bits)

    link = m.get("hf_url") or m.get("license_url") or ""
    link_html = f'<a href="{safe(link)}" target="_blank" rel="noopener" class="rc-link">Подробнее →</a>' if link else ""

    return f"""          <div class="release-card">
            <div class="rc-head">
              <div>
                <div class="rc-title">{safe(name)}{effort_badge(effort)}</div>
                <div class="rc-author">{safe(creator)}</div>
              </div>
              <span class="badge" style="background:{badge_bg};color:{badge_color}">{badge}</span>
            </div>
            <div class="rc-tags">
              <span class="badge">Intel {intel_str}</span>
              <span class="badge">{safe(meta)}</span>
            </div>
            {link_html}
          </div>"""


def render_releases_feed(aa_models):
    """Latest releases by releaseDate (AA)."""
    dated = [m for m in aa_models if m.get("release_date")]
    dated.sort(key=lambda m: m["release_date"], reverse=True)
    return "\n".join(render_aa_card(m) for m in dated[:RELEASES_LIMIT])


def render_top_open(aa_models):
    """Top open-source models by intelligenceIndex."""
    opens = [m for m in aa_models if m.get("is_open")]
    return "\n".join(render_aa_card(m) for m in opens[:RELEASES_LIMIT])


def render_arena_tables(arena_categories):
    if not arena_categories:
        return ""
    tabs_html = []
    tables_html = []
    first = True
    for cat in ARENA_CATEGORIES:
        models = arena_categories.get(cat, [])
        if not models:
            continue
        cat_name = ARENA_CATEGORY_NAMES.get(cat, cat)
        active = " active" if first else ""
        model_count = len(models)
        tabs_html.append(
            f'<button class="arena-tab{active}" data-arena="{safe(cat)}">{safe(cat_name)} <span style="opacity:0.5;font-size:0.6875rem">({model_count})</span></button>'
        )
        rows = []
        for j, m in enumerate(models[:30], 1):
            ci_str = f"&plusmn;{m['ci']}" if m.get("ci") else ""
            votes_str = fmt_count(m["votes"]) if m.get("votes") else "—"
            row_cls = ""
            if j == 1:
                row_cls = ' class="row-gold"'
            elif j == 2:
                row_cls = ' class="row-silver"'
            elif j == 3:
                row_cls = ' class="row-bronze"'
            rows.append(f"""                  <tr{row_cls}>
                    <td class="rank">{j}</td>
                    <td class="model-name"><span style="font-weight:600">{safe(m['model'])}</span><br/><span class="model-author">{safe(m.get('vendor', ''))}</span></td>
                    <td class="num" style="font-weight:600">{m['score']}</td>
                    <td class="num" style="color:hsl(240 5% 45%);font-size:0.6875rem">{ci_str}</td>
                    <td class="num">{votes_str}</td>
                  </tr>""")
        display = "block" if first else "none"
        rows_str = "\n".join(rows)
        tables_html.append(f"""            <div class="arena-panel" data-arena="{safe(cat)}" style="display:{display}">
              <table class="lb-table arena-table">
                <thead>
                  <tr>
                    <th class="rank">#</th>
                    <th>Модель</th>
                    <th class="num">Score</th>
                    <th class="num">CI</th>
                    <th class="num">Голоса</th>
                  </tr>
                </thead>
                <tbody>
{rows_str}
                </tbody>
              </table>
              <div style="text-align:right;font-size:0.6875rem;color:hsl(240 5% 35%);margin-top:0.5rem">{len(models)} open-source моделей</div>
            </div>""")
        first = False
    if not tabs_html:
        return ""
    return f"""          <div class="arena-tabs">
            {' '.join(tabs_html)}
          </div>
{chr(10).join(tables_html)}"""


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    log("=== LLM Bench update started ===")

    template_path = Path(TEMPLATE)
    if not template_path.exists():
        log(f"ERROR: Template not found: {TEMPLATE}")
        sys.exit(1)
    template = template_path.read_text(encoding="utf-8")

    aa_models = fetch_artificial_analysis()
    mmlu_models = fetch_mmlu_pro()
    arena_result = fetch_arena_categories()
    arena_all, arena_open = arena_result if arena_result else ({}, {})

    # Cache fallback
    cache_path = Path(CACHE)
    cache = {}
    cache_is_fresh = False
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_at = cache.get("updated", "")
            if cached_at:
                cache_dt = datetime.fromisoformat(cached_at)
                age_days = (datetime.now(MSK) - cache_dt).days
                cache_is_fresh = age_days < CACHE_MAX_AGE_DAYS
        except Exception:
            pass

    using_cache = False
    if not aa_models:
        if cache_is_fresh and cache.get("aa_models"):
            log("WARN: Using cached AA data")
            aa_models = cache["aa_models"]
            using_cache = True
        else:
            log("ERROR: AA fetch failed and cache is stale. Keeping current HTML.")
            sys.exit(0)

    if not arena_open and cache_is_fresh:
        arena_all = cache.get("arena_all", {})
        arena_open = cache.get("arena_open", {})

    # Merge MMLU
    if mmlu_models:
        merge_mmlu_into_aa(aa_models, mmlu_models)
    elif cache_is_fresh and cache.get("aa_models"):
        # restore mmlu from cache
        cached_mmlu = {_normalize(m["name"]): m.get("mmlu_pro")
                       for m in cache["aa_models"] if m.get("mmlu_pro") is not None}
        for am in aa_models:
            if am.get("mmlu_pro") is None:
                am["mmlu_pro"] = cached_mmlu.get(_normalize(am["name"]))

    lb_models = aa_models if LEADERBOARD_LIMIT is None else aa_models[:LEADERBOARD_LIMIT]

    # Save cache
    if not using_cache:
        try:
            cache_data = {
                "aa_models": aa_models,
                "arena_all": arena_all or {},
                "arena_open": arena_open or {},
                "updated": datetime.now(MSK).isoformat(),
            }
            cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            log(f"WARN: Failed to write cache: {e}")

    # Stats
    if using_cache and cache.get("updated"):
        cache_dt = datetime.fromisoformat(cache.get("updated"))
        last_updated = cache_dt.strftime("%d.%m.%Y %H:%M MSK")
    else:
        last_updated = datetime.now(MSK).strftime("%d.%m.%Y %H:%M MSK")
    model_count = str(len(lb_models))

    data_sources = sum(1 for x in [aa_models, mmlu_models, arena_all] if x)
    open_count = sum(1 for m in lb_models if m.get("is_open"))

    leaderboard_html = render_leaderboard_rows(lb_models)
    arena_html = render_arena_tables(arena_open or {})
    releases_html = render_releases_feed(aa_models)
    top_open_html = render_top_open(aa_models)

    arena_model_set = set()
    for cat_models in (arena_open or {}).values():
        for m in cat_models:
            arena_model_set.add(m["model"])
    arena_count = str(len(arena_model_set)) if arena_model_set else "0"

    html = template
    html = html.replace("{{LAST_UPDATED}}", last_updated)
    html = html.replace("{{MODEL_COUNT}}", model_count)
    html = html.replace("{{DATA_SOURCES}}", str(data_sources))
    html = html.replace("{{TOTAL_VOTES}}", str(open_count))
    html = html.replace("{{LEADERBOARD_ROWS}}", leaderboard_html)
    html = html.replace("{{ARENA_TABLES}}", arena_html)
    html = html.replace("{{ARENA_COUNT}}", arena_count)
    html = html.replace("{{RELEASES_FEED}}", releases_html)
    html = html.replace("{{TOP_DOWNLOADS}}", top_open_html)

    output_path = Path(OUTPUT)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    log(f"Written {output_path.stat().st_size:,} bytes to {OUTPUT}")
    log(f"Leaderboard: {len(lb_models)} AA models ({open_count} OSS)")
    log("=== Update complete ===")


if __name__ == "__main__":
    main()
