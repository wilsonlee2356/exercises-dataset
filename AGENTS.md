# AGENTS.md — Exercises Dataset

## Project Overview

This is a **data-centric repository, not a software package**. It ships a curated fitness
exercise dataset plus two standalone, dependency-free HTML tools to explore and integrate it.
There is no build system, no package manifest (no `package.json`, `pyproject.toml`, etc.),
no test suite, and no CI configuration.

**Contents (1,324 exercises):**

- `data/exercises.json` (~15 MB) — the primary artifact. A JSON array of 1,324 exercise records.
- `data/exercises.schema.json` — JSON Schema (Draft 2020-12) formally describing every record.
- `images/` — 1,324 × 180×180 JPG thumbnails (~11 MB).
- `videos/` — 1,324 × 180×180 animation GIFs (~125 MB).
- `index.html` (~15 MB) — self-contained interactive exercise browser. The **entire dataset is
  embedded** in it as a single-line JavaScript constant (`const EXERCISES = [...]`, on line ~1172).
- `setup.html` (~60 KB) — developer setup guide. Generates `CREATE TABLE` SQL (SQL Server,
  PostgreSQL, MySQL, SQLite) and ready-to-run `.sql` INSERT files, plus copy-paste API client
  examples (JavaScript, Python, C#, Java, PHP, Go, cURL) and an LLM prompt for generating a
  backend. Unlike `index.html`, it **fetches `data/exercises.json` lazily** (only when the user
  clicks "Generate SQL"), so that feature requires the page to be served over HTTP.
- `tools/reelgen/` — Python CLI + local web UI that turns the dataset into short-form
  "form check" reels (branded 1080×1920 MP4s + per-language narration scripts +
  MoneyPrinterTurbo API payloads). Outputs land in `reels_out/` (git-ignored).
  Requires a `.venv` with `pillow` + `imageio-ffmpeg`; see `tools/reelgen/README.md`.
- `MoneyPrinterTurbo/` (git-ignored, NOT part of this repo) — sibling checkout of
  `harry0703/MoneyPrinterTurbo` used by reelgen as the reel renderer (TTS, subtitles,
  BGM). Runs key-free for this pipeline; its venv is `MoneyPrinterTurbo/venv`
  (Python 3.11), start the API with `MoneyPrinterTurbo/venv/bin/python main.py`.
- `docker-compose.yml` + `tools/reelgen/Dockerfile` — containerized stack:
  `mpt-api` (MPT API, official-mirror build args) + `reelgen` (web UI, env-configured
  with `REELGEN_MPT_URL`/`REELGEN_MPT_STORAGE`), sharing `./MoneyPrinterTurbo/storage`
  as the materials handoff. `docker compose up --build -d` starts everything.
- `README.md` — full human documentation (statistics, schema, usage examples).
- `LICENSE` — MIT for code/data/instruction text **plus a MEDIA EXCEPTION** (see Security/Legal).
- `NOTICE.md` — Gym visual media attribution terms.

Upstream: `https://github.com/hasaneyldrm/exercises-dataset`. The dataset powers the LogPress app.

## Technology Stack & Runtime Architecture

- **Data:** plain JSON, UTF-8, read directly by consumers (`json.load`, `require`, pandas, etc.).
- **Tools:** vanilla HTML/CSS/JavaScript. Zero dependencies, zero build step.
  `index.html` works fully offline via `file://` because the data is baked in.
- **No runtime, server, or framework** exists in this repo.

## Data Model (per record in `data/exercises.json`)

| Field | Notes |
|---|---|
| `id` | String, zero-padded 4 digits (`"0001"`). Unique, but **not contiguous** (range `0001`–`5201`). |
| `name` | Exercise name, lowercase (e.g. `"3/4 sit-up"`). |
| `category` / `body_part` | Always identical values. `body_part` is an enum of 10: `back`, `cardio`, `chest`, `lower arms`, `lower legs`, `neck`, `shoulders`, `upper arms`, `upper legs`, `waist`. |
| `equipment` | Free-form lowercase string (e.g. `"body weight"`, `"dumbbell"`, `"barbell"`). |
| `instructions` | Object: full instruction text per language. **9 languages present in every record:** `en`, `es`, `it`, `tr`, `ru`, `zh`, `hi`, `pl`, `ko`. |
| `instruction_steps` | Object: same instructions as ordered `array[string]` of steps, same 9 languages. |
| `muscle_group` | Primary synergist muscle group. |
| `secondary_muscles` | `array[string]`. |
| `target` | Primary target muscle (e.g. `"abs"`, `"biceps"`). |
| `media_id` | Original Gym visual media reference (e.g. `"2gPfomN"`). |
| `image` / `gif_url` | Relative paths. **Strict naming convention:** `images/{id}-{media_id}.jpg` and `videos/{id}-{media_id}.gif` (verified for all 1,324 records). |
| `attribution` | Always exactly `© Gym visual — https://gymvisual.com/` — never change or omit. |
| `created_at` | ISO 8601 timestamp with timezone. |

Schema gotcha: the JSON Schema's `languageMap` only lists 6 languages (`en`, `es`, `it`, `tr`,
`ru`, `zh`) as `required` and allows the rest via `additionalProperties` — but the actual data
always carries all 9. Keep new records consistent with the data (9 languages), not just the schema.

## Development Conventions

- **Language of documentation/comments:** English. (Data itself is multilingual.)
- **Editing the dataset:**
  - Validate against `data/exercises.schema.json` after any change (`additionalProperties: false`,
    all 15 fields required).
  - New records need: a unique 4-digit zero-padded `id`, all 9 languages in both `instructions`
    and `instruction_steps`, matching media files at 180×180 named `{id}-{media_id}.{jpg,gif}`,
    and the exact `attribution` string above.
  - **Keep `index.html` in sync:** it embeds a full copy of the dataset in the `EXERCISES`
    constant. Any add/edit/remove in `exercises.json` must be regenerated into `index.html`
    (the whole array is serialized onto one line, no pretty-printing).
  - Keep `README.md` statistics (counts by body part / equipment) in sync when adding/removing records.
- **reelgen conventions:** the `© Gym visual` attribution is rendered onto every
  generated canvas from each record's `attribution` field — never remove it. Keep the
  tool dependency-light (stdlib + Pillow + ffmpeg binary), Python ≥ 3.9 compatible.
  `tools/reelgen/reelgen.py` is the CLI; `tools/reelgen/server.py` is a stdlib-only
  local web UI (serves `webui.html`, no framework) wrapping the same functions —
  keep both entry points working when changing rendering/payload logic.
- **HTML tools:** single-file style — inline `<style>` and `<script>`, no external assets,
  no frameworks. `index.html` uses CSS custom properties as design tokens, a state object +
  render functions, an IntersectionObserver for infinite scroll (page size 60), and a
  pre-computed lowercase `_idx` search string per exercise. Follow the existing patterns when editing.

## Build, Run & Test Commands

There is nothing to build. To work with the project:

```bash
# Open the browser app (fully offline-capable)
open index.html

# Serve the folder (needed for setup.html's SQL-generation fetch)
python3 -m http.server 8000   # then visit http://localhost:8000/setup.html

# Validate the dataset against its JSON Schema
python3 - <<'EOF'
import json
data = json.load(open("data/exercises.json"))
schema = json.load(open("data/exercises.schema.json"))
try:
    import jsonschema
    jsonschema.validate(data, schema)
    print("OK:", len(data), "records valid")
except ImportError:
    print("pip install jsonschema first (use a venv)")
EOF

# Sanity checks (uniqueness, media presence, naming convention)
python3 - <<'EOF'
import json, os
data = json.load(open("data/exercises.json"))
ids = [e["id"] for e in data]
assert len(set(ids)) == len(ids), "duplicate ids"
missing = [e["id"] for e in data if not os.path.exists(e["image"]) or not os.path.exists(e["gif_url"])]
print("records:", len(data), "| missing media:", len(missing))
EOF
```

**Testing strategy:** there are no automated tests. "Testing" a dataset change means (1) JSON
Schema validation and (2) media-integrity checks like the snippet above. For HTML changes, open
the page and exercise search/filters/modal/SQL-generation manually.

## Deployment

None. The repo is consumed by cloning/downloading. `index.html` and `setup.html` are static
files that can be hosted on any static file server as-is.

## Security & Legal Considerations

- **Media is NOT MIT-licensed.** `images/` and `videos/` are © Gym visual
  (https://gymvisual.com/), redistributed at 180×180 only, with written permission. The MIT
  license covers only code, dataset structure, and instruction text (see the MEDIA EXCEPTION in
  `LICENSE` and `NOTICE.md`). Never strip the `attribution` field, never upscale/redistribute the
  media beyond these terms, and never claim ownership of the exercise content.
- The dataset is for educational/research use; the repo disclaims ownership of the underlying
  exercise content.
- `.gitignore` excludes `.claude/` (local AI-tool settings — do not commit them), `.venv/`,
  `__pycache__/`, `.DS_Store`, and `*.zip`.
