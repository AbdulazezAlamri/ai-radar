"""AI Radar collector: fetches sources, dedupes, summarizes in Arabic, writes data/*.json."""
import hashlib, json, os, re, sys, time, html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser, requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CFG = json.loads((ROOT / "collector" / "sources.json").read_text(encoding="utf-8"))
NOW = datetime.now(timezone.utc)
RIYADH = NOW + timedelta(hours=3)
TODAY = RIYADH.strftime("%Y-%m-%d")
NO_LLM = "--no-llm" in sys.argv
GH_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {"User-Agent": "ai-radar/1.0 (+github actions)"}

PILLARS = {
    "models": "موديلات", "tools": "أدوات", "github": "GitHub", "research": "أبحاث", "banking": "بنوك",
    "saudi": "السعودية", "hackathon": "مسابقات", "funding": "صفقات",
}
SOURCE_CAT = {"tech": "أخبار تقنية", "research": "أبحاث", "github": "ريبو GitHub صاعد", "banking": "بنوك", "saudi": "السعودية", "vc": "استثمار"}
DEFAULT_PILLAR = {"tech": "models", "github": "github", "research": "research", "banking": "banking", "saudi": "saudi", "vc": "funding"}


def uid(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def clean(t, n=600):
    t = re.sub(r"<[^>]+>", " ", html.unescape(t or ""))
    return re.sub(r"\s+", " ", t).strip()[:n]


def norm_title(t):
    return re.sub(r"[^a-z0-9؀-ۿ]+", "", (t or "").lower())[:80]


def parse_date(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            try:
                return datetime(*e[k][:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def fetch_rss():
    out = []
    for src in CFG["rss"]:
        max_age = timedelta(hours=src.get("max_age_hours", CFG["limits"]["max_age_hours"]))
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=25)
            feed = feedparser.parse(r.content)
        except Exception as ex:
            print(f"[rss] {src['name']} failed: {ex}")
            continue
        kws = [k.lower() for k in src.get("keywords", [])]
        excl = [k.lower() for k in src.get("exclude", [])]
        n = 0
        for e in feed.entries[:40]:
            title = clean(e.get("title"), 200)
            link = e.get("link") or ""
            if not title or not link:
                continue
            d = parse_date(e)
            if d and NOW - d > max_age:
                continue
            text = (title + " " + clean(e.get("summary", ""))).lower()
            if kws and not any(k in text for k in kws):
                continue
            if excl and any(k in text for k in excl):
                continue
            out.append({
                "id": uid(link), "title": title, "url": link, "source": src["name"],
                "category": src["category"], "published": (d or NOW).isoformat(),
                "snippet": clean(e.get("summary", ""), 500),
            })
            n += 1
        print(f"[rss] {src['name']}: {n}")
    return out


def fetch_hn():
    c = CFG["hackernews"]
    out = []
    try:
        since = int((NOW - timedelta(hours=CFG["limits"]["max_age_hours"])).timestamp())
        r = requests.get("https://hn.algolia.com/api/v1/search", params={
            "tags": "story", "numericFilters": f"points>{c['min_points']},created_at_i>{since}", "hitsPerPage": 100,
        }, headers=HEADERS, timeout=25)
        for h in r.json().get("hits", []):
            title = h.get("title") or ""
            if not any(k.lower() in title.lower() for k in c["keywords"]):
                continue
            link = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            out.append({"id": uid(link), "title": title, "url": link, "source": f"Hacker News ({h.get('points')} pts)",
                        "category": "tech", "published": h.get("created_at"), "snippet": ""})
    except Exception as ex:
        print(f"[hn] failed: {ex}")
    print(f"[hn]: {len(out)}")
    return out


def fetch_github():
    c = CFG["github"]
    out, seen = [], set()
    since = (NOW - timedelta(days=c["days"])).strftime("%Y-%m-%d")
    hdr = dict(HEADERS, Accept="application/vnd.github+json")
    if GH_TOKEN:
        hdr["Authorization"] = f"Bearer {GH_TOKEN}"
    for topic in c["topics"]:
        try:
            r = requests.get("https://api.github.com/search/repositories", params={
                "q": f"topic:{topic} created:>{since} stars:>={c['min_stars']}",
                "sort": "stars", "order": "desc", "per_page": c["per_topic"],
            }, headers=hdr, timeout=25)
            for repo in r.json().get("items", []):
                if repo["full_name"] in seen:
                    continue
                seen.add(repo["full_name"])
                out.append({"id": uid(repo["html_url"]), "title": repo["full_name"], "url": repo["html_url"],
                            "source": f"GitHub ★{repo['stargazers_count']:,}", "category": "github",
                            "published": repo.get("pushed_at") or repo["created_at"],
                            "snippet": clean(repo.get("description") or "", 300),
                            "stars": repo["stargazers_count"], "lang": repo.get("language")})
            time.sleep(1.2)
        except Exception as ex:
            print(f"[github] {topic} failed: {ex}")
    out.sort(key=lambda x: -x.get("stars", 0))
    print(f"[github]: {len(out)}")
    return out


def fetch_hf_papers():
    out = []
    try:
        r = requests.get("https://huggingface.co/api/daily_papers", params={"limit": CFG["hf_papers"]["limit"]},
                         headers=HEADERS, timeout=25)
        for p in r.json():
            paper = p.get("paper", {})
            pid = paper.get("id")
            if not pid:
                continue
            link = f"https://huggingface.co/papers/{pid}"
            out.append({"id": uid(link), "title": clean(paper.get("title"), 200), "url": link,
                        "source": f"HF Papers 👍{paper.get('upvotes', 0)}", "category": "research",
                        "published": p.get("publishedAt") or NOW.isoformat(), "snippet": clean(paper.get("summary", ""), 700)})
    except Exception as ex:
        print(f"[hf] failed: {ex}")
    print(f"[hf]: {len(out)}")
    return out


def dedupe(items, seen_ids):
    out, titles = [], set()
    for it in items:
        nt = norm_title(it["title"])
        if it["id"] in seen_ids or nt in titles:
            continue
        titles.add(nt)
        out.append(it)
    return out

DEDUPE_SCHEMA = {
    "type": "object",
    "properties": {"drop": {"type": "array", "items": {"type": "string"}}},
    "required": ["drop"], "additionalProperties": False,
}


def recent_titles(days=7):
    out = []
    for p in sorted(DATA.glob("20??-??-??.json"), reverse=True)[:days]:
        if p.stem == TODAY:
            continue
        for it in json.loads(p.read_text(encoding="utf-8")).get("items", []):
            out.append(it.get("title_en") or it.get("title") or "")
    return [t for t in out if t][:200]


def semantic_dedupe(items):
    """One cheap model call on titles: drop items that cover a story already in today's list or published recently."""
    if NO_LLM or not os.environ.get("ANTHROPIC_API_KEY") or len(items) < 2:
        return items
    import anthropic
    cands = [{"id": it["id"], "title": it["title"], "source": it["source"], "has_text": len(it.get("snippet") or "") > 80}
             for it in items[:200]]
    payload = {"candidates": cands, "published_recently": recent_titles()}
    prompt = (
        "You deduplicate a daily AI news feed. Two items are the SAME STORY when they report the same event, deal, "
        "release or announcement, even in different languages or from different outlets. "
        "Return the ids to DROP: "
        "1. Among candidates covering the same story, keep exactly one (prefer has_text=true, then the more specific title) and drop the rest. "
        "2. Drop any candidate whose story already appears in published_recently. "
        "Different stories about the same company or topic are NOT duplicates. When unsure, keep. "
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        resp = anthropic.Anthropic().messages.create(
            model="claude-haiku-5-5", max_tokens=16000,
            system="You are a precise deduplication filter. Output only the JSON object.",
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": DEDUPE_SCHEMA}},
        )
        if resp.stop_reason != "end_turn":
            raise RuntimeError(f"stop_reason={resp.stop_reason}")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise RuntimeError(f"no text block: {[b.type for b in resp.content]}")
        drop = set(json.loads(text)["drop"])
        kept = [it for it in items if it["id"] not in drop]
        print(f"[dedupe] model dropped {len(items) - len(kept)} near-duplicates (in={resp.usage.input_tokens} out={resp.usage.output_tokens})")
        return kept
    except Exception as ex:
        print(f"[dedupe] model step failed, keeping all: {ex!r}")
        return items


def cap(items):
    """Pre-summarize cap per source category (keeps the LLM bill bounded)."""
    lim = CFG["limits"]["pre"]
    by = {}
    for it in sorted(items, key=lambda x: x.get("published") or "", reverse=True):
        by.setdefault(it["category"], [])
        if len(by[it["category"]]) < lim.get(it["category"], 6):
            by[it["category"]].append(it)
    return [it for cat in lim for it in by.get(cat, [])]


def select(items):
    """After scoring: drop low-relevance items, then cap per pillar by relevance and importance."""
    lim, min_rel = CFG["limits"]["final"], CFG["limits"].get("min_relevance", 3)
    for it in items:
        if int(it.get("relevance", 3)) < min_rel:
            print(f"[select] drop rel={it.get('relevance')} {it['pillar']:9} {it['title'][:70]}")
    by = {}
    for it in sorted(items, key=lambda x: (-int(x.get("relevance", 3)), -int(x.get("importance", 3)))):
        if int(it.get("relevance", 3)) < min_rel:
            continue
        by.setdefault(it["pillar"], [])
        if len(by[it["pillar"]]) < lim.get(it["pillar"], 6):
            by[it["pillar"]].append(it)
    return [it for p in PILLARS for it in by.get(p, [])]


SYSTEM = """أنت محرر نشرة يومية لمهندس ذكاء اصطناعي يعمل في بنك سعودي. نطاق عمله: (1) ابتكار حلول وبناء POCs، (2) متابعة التقنيات والموديلات الجديدة، (3) كتابة أبحاث للنشر، (4) متابعة الاستثمار الجريء بشكل ثانوي.
لكل عنصر أعد الحقول التالية:
- title_ar / title_en: عنوان قصير وجذاب (أقل من 12 كلمة). أبقِ أسماء المنتجات والموديلات والريبوهات بالإنجليزية في النسختين.
- summary_ar / summary_en: ملخص من 2 إلى 4 جمل يشرح ما الجديد فعلياً، بدون حشو.
- why_ar / why_en: جملة واحدة: لماذا يهم هذا المهندس تحديداً.
- tags: 2 إلى 4 وسوم قصيرة بالإنجليزية.
- importance: 1 إلى 5، حجم الخبر في عالم AI (5 = حدث كبير).
- relevance: 0 إلى 5، مدى صلته بعمل هذا المهندس تحديداً. هذا الحقل هو بوابة النشر: ما تحت 3 لا يُنشر.
- poc: true فقط إذا كان في العنصر شيء يمكنه تجربته أو بناؤه فعلاً خلال أيام (أداة، ريبو، API، تقنية جديدة لها استخدام في بنك). وإلا false.
- pillar: التصنيف، واحد فقط من الثمانية أدناه.

التصنيفات (اختر حسب "ما هو الخبر"، لا حسب من نشره):
- models: موديلات جديدة أو تحديثاتها، تقنيات وقدرات جديدة، إعلانات مختبرات AI التقنية، benchmarks، inference، agents. مثال: "Qwen يطلق موديل 27B"، "OpenAI تضيف ميزة memory".
- tools: أدوات ومكتبات وإصدارات برمجية ومنتجات للمطورين تُعلن في مدونة أو خبر: frameworks، SDKs، MCP servers، إصدارات نسخ. مثال: "llm 0.37 released"، "Hugging Face تطلق مكتبة جديدة".
- github: حصرياً العناصر التي source_type فيها "ريبو GitHub صاعد". كل ريبو من هذا المصدر يأخذ github دائماً مهما كان محتواه، ولا يأخذه أي عنصر من مصدر آخر.
- research: أوراق علمية، دراسات، تقارير بحثية، مؤتمرات أكاديمية. مثال: أي ورقة من Hugging Face Papers.
- banking: استخدام AI في البنوك والمدفوعات والتمويل والاحتيال والامتثال والبنوك المركزية. مثال: "Goldman يمنع أدوات AI coding"، "دليل البنك المركزي حول AI".
- saudi: أي خبر AI يخص السعودية أو الخليج: شركات، شراكات، SDAIA، HUMAIN، بنية تحتية، سياسات. مثال: "Aramco تستحوذ على حصة في HUMAIN"، "شراكة Tencent وOmniOps في السعودية".
- hackathon: هاكاثونات ومسابقات وجوائز وتحديات يمكن للمهندس المشاركة فيها أو التقديم عليها. فقط هذا المعنى. مثال: "فتح التسجيل في هاكاثون المدينة للذكاء الاصطناعي".
- funding: جولات تمويل، استحواذات، IPO، صفقات استثمار في شركات AI. مثال: "Trajectory ترفع 45 مليون دولار".

قواعد حاسمة في التصنيف:
- "منافسة" بين الشركات أو نمو الإيرادات أو تقييم شركة ليس hackathon أبداً. إيرادات Anthropic تذهب إلى funding أو models حسب المحتوى.
- التسريحات، الدعاوى القضائية، بيع الأسهم، أرباح البنوك بدون AI، التصريحات العامة: ليست banking ولا funding. أعطها relevance منخفضاً.
- أولوية saudi: إذا كان الخبر سعودياً أو خليجياً فهو saudi حتى لو كان صفقة، إلا الهاكاثونات والجوائز فتبقى hackathon.
- ورقة بحثية عن AI في المال تذهب إلى research، وليس banking.

معايير relevance (مهمة جداً):
- 5: يجب ألا يفوته: موديل كبير جديد، أداة يستطيع تجربتها فوراً في عمله، خبر سعودي مهم، هاكاثون مفتوح للتسجيل.
- 4: مهم لعمله أو أبحاثه بشكل مباشر.
- 3: مفيد للاطلاع العام في مجال AI.
- 2: هامشي: ميزة استهلاكية، خبر إقليمي خارج الخليج لا يؤثر عليه، نقاش رأي، تنبؤات.
- 0 أو 1: لا يهمه إطلاقاً: رياضة، ترفيه، دعاية مؤتمرات وتذاكر، تسريحات، بيع أسهم، أخبار شركات عامة بلا محتوى تقني، توسيع منتج استهلاكي إلى سوق أو لغة خارج المنطقة العربية.
أمثلة: "Google توسع تطبيق قصص AI إلى الهند بـ13 لغة هندية" تأخذ relevance 1. "جائزة أفضل مدرب في الدوري السعودي" تأخذ 0. "Oracle تبيع أسهماً بـ20 مليار" تأخذ 1. "Goldman يمنع المتداولين من AI coding tools" تأخذ 4. "ريبو agent framework وصل 3000 نجمة" تأخذ 4 مع poc true وتصنيف github.

قاعدة المصطلحات في النسخة العربية (مهمة جداً):
- لا تترجم ولا تعرّب ولا تكتب بحروف عربية أي مصطلح تقني أو اسم أداة أو مكتبة أو إطار عمل أو موديل أو شركة أو مفهوم تقني. اكتبه بالإنجليزية كما هو داخل الجملة العربية، بدون أقواس ولا شرح مكرر.
- يشمل ذلك مثلاً: RAG, fine-tuning, embeddings, transformer, inference, agent, benchmark, open-source, LLM, API, token, latency, prompt, dataset, GPU, LangChain, PyTorch, Hugging Face, Claude, GPT, Llama, MCP, vector database.
- صحيح: "الفريق أطلق موديل open-source يعتمد على RAG مع تحسين في inference latency".
- خطأ: "الفريق أطلق نموذجاً مفتوح المصدر يعتمد على التوليد المعزز بالاسترجاع مع تحسين في زمن الاستدلال".
- الكلمات العامة غير التقنية تبقى عربية: فريق، أطلق، نتائج، تحسين، شركة، دراسة.
- اجعل الجملة العربية سليمة نحوياً مع الكلمات الإنجليزية داخلها، ولا تضع علامات ترقيم إنجليزية ملتصقة بالكلمة الإنجليزية في نهاية الجملة العربية.
لا تخترع معلومات غير موجودة في النص. إن كان النص فارغاً فاعتمد على العنوان فقط وكن حذراً."""

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "title_ar": {"type": "string"}, "summary_ar": {"type": "string"},
            "why_ar": {"type": "string"}, "title_en": {"type": "string"}, "summary_en": {"type": "string"},
            "why_en": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
            "importance": {"type": "integer"}, "relevance": {"type": "integer"}, "poc": {"type": "boolean"},
            "pillar": {"type": "string", "enum": list(PILLARS)},
        },
        "required": ["id", "title_ar", "summary_ar", "why_ar", "title_en", "summary_en", "why_en", "tags", "importance", "relevance", "poc", "pillar"],
        "additionalProperties": False,
    }}},
    "required": ["items"], "additionalProperties": False,
}


def fill_defaults(it):
    it.setdefault("title_ar", it["title"])
    it.setdefault("summary_ar", it["snippet"] or it["title"])
    it.setdefault("why_ar", "")
    it.setdefault("title_en", it["title"])
    it.setdefault("summary_en", it["snippet"] or it["title"])
    it.setdefault("why_en", "")
    it.setdefault("tags", [])
    it.setdefault("importance", 3)
    it.setdefault("relevance", 3)
    it.setdefault("poc", False)
    it.setdefault("pillar", DEFAULT_PILLAR.get(it["category"], "models"))


def summarize(items):
    if NO_LLM or not os.environ.get("ANTHROPIC_API_KEY"):
        print("[llm] skipped (no key or --no-llm)")
        for it in items:
            fill_defaults(it)
        return items
    import anthropic
    client = anthropic.Anthropic()
    by_id = {it["id"]: it for it in items}
    for i in range(0, len(items), 6):
        batch = items[i:i + 6]
        payload = [{"id": b["id"], "source": b["source"], "source_type": SOURCE_CAT[b["category"]],
                    "title": b["title"], "text": b["snippet"]} for b in batch]
        try:
            resp = client.messages.create(
                model="claude-haiku-5-5", max_tokens=16000, system=SYSTEM,
                messages=[{"role": "user", "content": "لخّص هذه العناصر وأعد JSON فقط:\n" + json.dumps(payload, ensure_ascii=False)}],
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            )
            if resp.stop_reason != "end_turn":
                print(f"[llm] batch {i // 6 + 1} stopped early: {resp.stop_reason}")
                continue
            text = next(b.text for b in resp.content if b.type == "text")
            for s in json.loads(text)["items"]:
                if s["id"] in by_id:
                    by_id[s["id"]].update(s)
            print(f"[llm] batch {i // 6 + 1}: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
        except Exception as ex:
            print(f"[llm] batch {i // 6 + 1} failed: {ex}")
    for it in items:
        fill_defaults(it)
    return items


def main():
    DATA.mkdir(exist_ok=True)
    seen_path = DATA / "seen.json"
    seen = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
    cutoff = (NOW - timedelta(days=14)).isoformat()
    seen = {k: v for k, v in seen.items() if v > cutoff}
    today_path = DATA / f"{TODAY}.json"
    if today_path.exists():  # re-run on the same day: rebuild today's set instead of hiding it
        for it in json.loads(today_path.read_text(encoding="utf-8")).get("items", []):
            seen.pop(it["id"], None)

    items = fetch_rss() + fetch_hn() + fetch_github() + fetch_hf_papers()
    items = cap(semantic_dedupe(dedupe(items, set(seen))))
    print(f"[total] {len(items)} candidates to score")
    items = select(summarize(items))
    items.sort(key=lambda x: (-int(x.get("relevance", 3)), -int(x.get("importance", 3))))

    day = {"date": TODAY, "generated_at": NOW.isoformat(), "count": len(items), "pillars": PILLARS, "items": items}
    (DATA / f"{TODAY}.json").write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
    (DATA / "latest.json").write_text(json.dumps(day, ensure_ascii=False, indent=1), encoding="utf-8")
    for it in items:
        seen[it["id"]] = NOW.isoformat()
    seen_path.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    dates = sorted([p.stem for p in DATA.glob("20??-??-??.json")], reverse=True)
    (DATA / "index.json").write_text(json.dumps({"dates": dates}, ensure_ascii=False), encoding="utf-8")
    print(f"[done] wrote data/{TODAY}.json with {len(items)} items")


if __name__ == "__main__":
    main()
