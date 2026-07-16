# reelgen — short-form "form check" reel generator

Turns the exercises dataset into vertical (1080×1920) short-video building blocks,
and optionally hands them off to a local [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)
instance which adds TTS voiceover, subtitles, and background music.

For every `(exercise, language)` pair it produces:

| File | What it is |
|---|---|
| `card.png` | Branded canvas (name, target, equipment, accent color per body part) |
| `material.mp4` | Canvas + looped exercise GIF composited by ffmpeg |
| `script.txt` | Narration script: hook → numbered `instruction_steps[lang]` → closer |
| `payload.json` | Ready-to-POST MoneyPrinterTurbo `/api/v1/videos` request |
| `caption.txt` | Social caption: localized title + CTA + attribution + hashtags |
| `final.mp4` | The finished reel (only with `--send --wait`) |

## Retention scripts (hook bank + mistakes style)

Two script styles, selected with `--style` (default: `mistakes`):

- **`mistakes`** — retention-optimized: opens with a rotated pain/curiosity hook
  ("Most people do X wrong…", "If X never hits your {target}…", "The biggest X
  mistake happens on the first rep…"), reframes steps as "Fix #1, #2…", and ends
  with a loop-teaser follow CTA.
- **`tutorial`** — the classic "How to do X + Step 1..N + target/equipment closer".

Hooks (4 per language) and TTS voices (2 per language) rotate **deterministically
by exercise id**, so a feed of consecutive reels stays varied and re-running a
batch reproduces the same choices. Voice rate defaults to `1.15` (shorts pacing;
override with `--voice-rate 1.0`).

```bash
$PY tools/reelgen/reelgen.py script --id 0025 --lang en --style mistakes
$PY tools/reelgen/reelgen.py batch --lang en --style tutorial --voice-rate 1.0 --limit 10
```

## Publishing (captions)

```bash
# Preview a caption
$PY tools/reelgen/reelgen.py caption --id 0294 --lang en,es,ko
```

Every batch job writes a `caption.txt` next to the video: localized title,
follow CTA, hashtags (per-language generic + exercise-specific), and the
`© Gym visual` attribution line — keep it when posting.

The attribution string from each record (`© Gym visual — https://gymvisual.com/`)
is rendered onto every canvas. **It is required by the media license — do not remove it.**

## Skill journeys (calisthenics ladders)

`data/progressions.json` defines 9 skill ladders (push-up, pull-up, dip,
muscle-up, pistol-squat, handstand, planche, front-lever, l-sit) as ordered
rungs referencing exercise ids, each with a suggested rep/hold `goal`.

The `journey` subcommand renders a whole ladder as a numbered series —
"Road to Planche · Step 3/5" — with a journey hook ("step N of M"), tutorial
steps, and a next-rung teaser closer (final rung = "skill unlocked" closer).
The step counter is the subscribe hook: viewers follow to see the next rung.

```bash
# One ladder, one language
$PY tools/reelgen/reelgen.py journey --skill planche --lang en

# Everything: 9 skills x 9 languages, sent to MPT
$PY tools/reelgen/reelgen.py journey --skill all --lang en,es,it,tr,ru,zh,hi,pl,ko \
    --send --wait --mpt-storage $PWD/MoneyPrinterTurbo/storage
```

Journey jobs land in `reels_out/journeys/<skill>/<lang>/NN-<id>-<slug>/` so
they never collide with plain batch output. Skill names stay in English
(international calisthenics terms); hooks/closers/captions are localized.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install pillow imageio-ffmpeg   # imageio-ffmpeg bundles an ffmpeg binary
```

(Or use a system ffmpeg — `brew install ffmpeg` — and skip imageio-ffmpeg.)

## Web UI

Prefer clicking over typing? A local browser UI wraps the whole pipeline
(stdlib-only server, no extra dependencies):

```bash
.venv/bin/python tools/reelgen/server.py          # opens http://127.0.0.1:8321
```

Three columns: **1 · pick exercises** (search / body-part / equipment filters,
checkboxes), **2 · preview** (card image, rendered material video, narration
script per language), **3 · generate** (language multi-select, duration,
optional MPT send + ping test, live progress log, inline playback of finished
`final.mp4` reels). It uses the same rendering code as the CLI, so CLI and UI
outputs are interchangeable.

## Usage

```bash
PY=.venv/bin/python

# Preview the branded canvas for one exercise
$PY tools/reelgen/reelgen.py card --id 0025

# Render the 1080x1920 material MP4 (GIF composited into the canvas)
$PY tools/reelgen/reelgen.py material --id 0025 --duration 20

# Print the narration script (any of: en es it tr ru zh hi pl ko)
$PY tools/reelgen/reelgen.py script --id 0025 --lang en,es,zh

# Batch: material + script + payload for a filtered set of exercises
$PY tools/reelgen/reelgen.py batch --equipment dumbbell --lang en,es --limit 30
$PY tools/reelgen/reelgen.py batch --body-part chest --lang en --limit 10
```

Output goes to `reels_out/<lang>/<id>-<slug>/` (git-ignored), journeys to
`reels_out/journeys/<skill>/<lang>/NN-<id>-<slug>/`.

## Docker (recommended)

One command builds and starts **both** services (MPT API + reelgen UI):

```bash
docker compose up --build -d
open http://127.0.0.1:8321
```

- `mpt-api` — MoneyPrinterTurbo API (built from `MoneyPrinterTurbo/Dockerfile`,
  official mirrors via build args), API on `127.0.0.1:8080`
- `reelgen` — the web UI on `127.0.0.1:8321`, pre-configured via env
  (`REELGEN_MPT_URL=http://mpt-api:8080`, `REELGEN_MPT_STORAGE=/mpt-storage`)
- The materials handoff is the shared bind mount `./MoneyPrinterTurbo/storage`;
  finished reels land in `./reels_out/` on the host

```bash
docker compose logs -f reelgen      # watch the UI/batch logs
docker compose exec reelgen python tools/reelgen/reelgen.py batch \
    --lang en --limit 30 --duration 60 --send --wait \
    --mpt-url http://mpt-api:8080 --mpt-storage /mpt-storage   # CLI inside Docker
docker compose down                 # stop everything
```

Local (non-Docker) setup still works — see below.

## MoneyPrinterTurbo setup (verified local install)

MoneyPrinterTurbo lives as a **git-ignored sibling checkout** in this folder
(not vendored — keeps upstream updates a `git pull` away):

```bash
git clone --depth 1 https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
python3.11 -m venv venv && ./venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml          # no API keys needed for this pipeline
./venv/bin/python main.py                   # API on http://127.0.0.1:8080
```

**Zero API keys required**: reelgen supplies the script (no LLM), local materials
(no Pexels/Pixabay), and edge-TTS voices (free). MPT only adds voiceover,
subtitles, and BGM.

## Sending to MoneyPrinterTurbo

1. Run MoneyPrinterTurbo locally (its API listens on `http://127.0.0.1:8080`).
2. Point reelgen at MPT's `storage/` directory — local materials **must** live
   under `storage/local_videos/`, so reelgen copies each `material.mp4` there:

```bash
$PY tools/reelgen/reelgen.py batch --lang en --limit 30 \
    --send --wait \
    --mpt-url http://127.0.0.1:8080 \
    --mpt-storage /path/to/MoneyPrinterTurbo/storage
```

`--send` POSTs each `payload.json`; `--wait` polls the task and downloads the
finished reel as `final.mp4`. All payloads are submitted first and polled
afterwards — MPT runs `max_concurrent_tasks` (default 5) in parallel, so wall
time is ~ceil(N/5) × per-task time (measured: 6 reels in 4m17s vs ~13m serial).
Without `--send`, you can POST the payloads yourself:

```bash
curl -X POST http://127.0.0.1:8080/api/v1/videos \
  -H 'Content-Type: application/json' \
  --data-binary @reels_out/en/0025-barbell-bench-press/payload.json
```

## Notes & limits

- **TTS voices** default to edge-tts voices per language (see `VOICES` in
  `reelgen.py`); override with `--voice`.
- **Subtitle fonts:** MPT's default font covers Latin/CJK; for Hindi or Korean
  subtitles you may need to configure a matching font in MPT.
- **GIF resolution:** source media is 180×180 (per the Gym visual license). The
  default 540px display size is a plain upscale of that asset; for sharper reels,
  license higher-resolution clips directly from Gym visual and pass `--gif-scale`.
- **Exercise names** are English in the dataset, so non-English hooks/closers keep
  the English exercise name — intentional for the "gym vocabulary" crossover angle.
