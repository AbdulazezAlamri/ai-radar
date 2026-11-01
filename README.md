# رادار الذكاء الاصطناعي

نشرة صباحية شخصية تُبنى تلقائياً كل يوم على GitHub Actions وتُعرض عبر GitHub Pages.

## كيف تعمل

1. `collector/collect.py` يسحب المصادر المعرّفة في `collector/sources.json` (RSS، Hacker News، GitHub، Hugging Face Papers).
2. يزيل المكرر وما سبق عرضه خلال 14 يوماً، ثم يلخّص كل عنصر بالعربية عبر Claude Haiku.
3. يكتب `data/YYYY-MM-DD.json` و`data/latest.json` و`data/index.json` ويرفعها إلى الريبو.
4. `index.html` صفحة واحدة للجوال تعرض البطاقات، وزر "تعمّق" يفتح Issue بوسم `deep-dive` تصبح مهمة متابعة.

## الإعداد مرة واحدة

- أضف مفتاح Anthropic كـ Secret باسم `ANTHROPIC_API_KEY`.
- فعّل GitHub Pages من الفرع `main` والمجلد `/ (root)`.
- شغّل الـ workflow يدوياً أول مرة من تبويب Actions.

## التخصيص

- المصادر والحدود اليومية: `collector/sources.json`.
- أسلوب التلخيص: المتغير `SYSTEM` في `collector/collect.py`.
- موعد التشغيل: `cron` في `.github/workflows/daily.yml` (بتوقيت UTC).

## تشغيل محلي بدون تلخيص

```bash
pip install -r collector/requirements.txt
python collector/collect.py --no-llm
```
