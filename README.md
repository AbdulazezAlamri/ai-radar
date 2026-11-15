# AI Radar

A personal daily AI briefing, built automatically every morning on GitHub Actions and served as a mobile-friendly page on GitHub Pages. No server, no database.

**Live page:** https://abdulazezalamri.github.io/ai-radar/

## What it does

Every morning the collector gathers AI news, trending GitHub repositories, new papers, AI-in-banking news, Saudi AI news, and hackathons. It removes duplicates, scores each item for relevance, and writes a short bilingual summary (Arabic and English) with Claude Haiku. The page shows the result as short cards you can read in a few minutes.

## How it works

1. `collector/collect.py` pulls the sources defined in `collector/sources.json`: RSS feeds, Hacker News, the GitHub Search API, and Hugging Face daily papers.
2. Exact duplicates and anything shown in the last 14 days are dropped. A cheap model pass over titles then drops near-duplicates, including stories already published in the last 7 days.
3. Each remaining item is summarized in Arabic and English and given a category, an importance score, a relevance score, and a POC flag. Items with relevance below 3 are not published.
4. The run writes `data/YYYY-MM-DD.json`, `data/latest.json`, and `data/index.json`, and commits them to the repository.
5. `index.html` is a single static page that reads those JSON files.

## Categories

| Key | Meaning |
|---|---|
| `models` | New models, capabilities, and lab announcements |
| `tools` | Libraries, releases, and developer tools |
| `github` | Fast-rising new repositories |
| `research` | Papers and studies |
| `banking` | AI in banking, payments, and finance |
| `saudi` | AI news from Saudi Arabia and the Gulf |
| `hackathon` | Hackathons, competitions, and awards |
| `funding` | Funding rounds, acquisitions, and deals |

GitHub repositories are selected from six topics (`llm`, `ai-agents`, `generative-ai`, `machine-learning`, `rag`, `mcp`), created in the last 21 days with at least 300 stars.

## Page features

- Arabic and English, switchable globally or per card. Technical terms stay in English inside the Arabic text.
- Mark a card as read to move it to a collapsed section at the bottom.
- "Deep dive" opens a prefilled GitHub Issue with the `deep-dive` label, which then appears in the Deep dives tab as a follow-up task.
- Read aloud with the browser's built-in speech.
- Light and dark mode follow the device setting.
- Optional sync of read and deep-dive state across devices, stored in `state.json` on the `state` branch. It needs a fine-grained GitHub token with Contents read and write on this repository only, entered in the page under More, then Sync. The token stays in the browser and is never committed.

## Setup for your own copy

1. Fork or clone the repository.
2. Add your Anthropic API key as a repository secret named `ANTHROPIC_API_KEY`.
3. Enable GitHub Pages from the `main` branch, root folder.
4. Create an orphan branch named `state` containing `state.json` with `{"read":{},"deep":{},"updated":null}` if you want sync.
5. Run the workflow once from the Actions tab.

## Customizing

- Sources, per-category limits, and the relevance threshold: `collector/sources.json`.
- Summary style, category rules, and relevance criteria: the `SYSTEM` prompt in `collector/collect.py`.
- Schedule: the `cron` entries in `.github/workflows/daily.yml`, in UTC. There are three slots because GitHub can delay or skip scheduled runs. A guard ensures each day is built only once.

## Run locally without the model

```bash
pip install -r collector/requirements.txt
python collector/collect.py --no-llm
```
