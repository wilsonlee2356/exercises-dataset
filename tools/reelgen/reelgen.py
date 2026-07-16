#!/usr/bin/env python3
"""
reelgen — generate short-form "form check" reels from the exercises dataset,
optionally feeding them into a local MoneyPrinterTurbo instance.

Pipeline per (exercise, language):
  1. card     — branded 1080x1920 canvas (Pillow), with attribution baked in
  2. material — canvas + looped exercise GIF -> MP4 (ffmpeg)
  3. script   — narration text built from instruction_steps[lang]
  4. payload  — MoneyPrinterTurbo /api/v1/videos request JSON
  5. (opt) send the payload to MPT, poll the task, download the final reel

Requires: Pillow (pip), and an ffmpeg binary (system ffmpeg, or the one bundled
with the imageio-ffmpeg pip package, or --ffmpeg /path/to/ffmpeg).

Media note: exercise GIFs are © Gym visual (see NOTICE.md). The attribution
string from each record is rendered onto every canvas. Do not remove it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_DATA = os.path.join(REPO_ROOT, "data", "exercises.json")
DEFAULT_OUT = os.path.join(REPO_ROOT, "reels_out")

LANGS = ["en", "es", "it", "tr", "ru", "zh", "hi", "pl", "ko"]

# edge-tts voices accepted by MoneyPrinterTurbo (voice_name format: "<voice>-<gender>")
VOICES = {
    "en": "en-US-AriaNeural-Female",
    "es": "es-ES-ElviraNeural-Female",
    "it": "it-IT-ElsaNeural-Female",
    "tr": "tr-TR-EmelNeural-Female",
    "ru": "ru-RU-SvetlanaNeural-Female",
    "zh": "zh-CN-XiaoxiaoNeural-Female",
    "hi": "hi-IN-SwaraNeural-Female",
    "pl": "pl-PL-ZofiaNeural-Female",
    "ko": "ko-KR-SunHiNeural-Female",
}

HOOKS = {
    "en": "How to do {name} with perfect form.",
    "es": "Cómo hacer {name} con la forma correcta.",
    "it": "Come eseguire {name} con la tecnica corretta.",
    "tr": "{name} hareketini doğru formda nasıl yaparsın.",
    "ru": "Как правильно выполнять: {name}.",
    "zh": "如何用正确的姿势完成{name}。",
    "hi": "{name} को सही फॉर्म से करने का तरीका।",
    "pl": "Jak prawidłowo wykonać: {name}.",
    "ko": "{name}을(를) 올바른 자세로 하는 방법.",
}

CLOSERS = {
    "en": "Target muscle: {target}. Equipment: {equipment}. Save this for your next workout.",
    "es": "Músculo objetivo: {target}. Equipo: {equipment}. Guárdalo para tu próximo entrenamiento.",
    "it": "Muscolo target: {target}. Attrezzatura: {equipment}. Salvalo per il prossimo allenamento.",
    "tr": "Hedef kas: {target}. Ekipman: {equipment}. Bir sonraki antrenmanın için kaydet.",
    "ru": "Целевая мышца: {target}. Оборудование: {equipment}. Сохрани для следующей тренировки.",
    "zh": "目标肌肉：{target}。器械：{equipment}。收藏起来，下次训练用。",
    "hi": "लक्ष्य मांसपेशी: {target}। उपकरण: {equipment}। अपनी अगली कसरत के लिए सेव करें।",
    "pl": "Mięsień docelowy: {target}. Sprzęt: {equipment}. Zapisz na kolejny trening.",
    "ko": "타겟 근육: {target}. 장비: {equipment}. 꼭 저장해 두세요.",
}

STEP_LABELS = {
    "en": "Step {n}",
    "es": "Paso {n}",
    "it": "Passo {n}",
    "tr": "Adım {n}",
    "ru": "Шаг {n}",
    "zh": "第{n}步",
    "hi": "चरण {n}",
    "pl": "Krok {n}",
    "ko": "{n}단계",
}

# Accent color per body part — keeps the feed visually varied.
ACCENTS = {
    "back": "#4C8DFF",
    "cardio": "#FF5A5A",
    "chest": "#FF7A45",
    "lower arms": "#B388FF",
    "lower legs": "#4CD6C0",
    "neck": "#FFD54C",
    "shoulders": "#5AC8FF",
    "upper arms": "#FF5CA8",
    "upper legs": "#7CE05C",
    "waist": "#FFA94C",
}

# Canvas layout (1080x1920). The ffmpeg overlay must match these coordinates.
W, H = 1080, 1920
BG_COLOR = "#101014"
CARD_COLOR = "#1C1C22"
CARD_X, CARD_Y, CARD_SIZE, CARD_RADIUS = 190, 660, 700, 48
GIF_SIZE_DEFAULT = 540  # display upscale of the 180px source; see --gif-scale help
BRAND_LABEL = "F O R M  C H E C K"

FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_REG = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def load_exercises(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60]


def select_exercises(exercises, args):
    out = exercises
    if getattr(args, "ids", None):
        wanted = {i.strip() for i in args.ids.split(",")}
        out = [e for e in out if e["id"] in wanted]
    if getattr(args, "body_part", None):
        out = [e for e in out if e["body_part"] == args.body_part]
    if getattr(args, "equipment", None):
        out = [e for e in out if e["equipment"] == args.equipment]
    if getattr(args, "limit", None):
        out = out[: args.limit]
    return out


def find_ffmpeg(cli_value=None):
    if cli_value:
        return cli_value
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit(
            "ffmpeg not found. Install it (brew install ffmpeg) or "
            "'pip install imageio-ffmpeg', or pass --ffmpeg /path/to/ffmpeg."
        )


def load_font(candidates, size):
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


# --------------------------------------------------------------------------
# 1. Card rendering (Pillow)
# --------------------------------------------------------------------------


def render_card(exercise, out_png):
    accent = ACCENTS.get(exercise["body_part"], "#FF7A45")
    img = Image.new("RGB", (W, H), BG_COLOR)
    d = ImageDraw.Draw(img)

    f_label = load_font(FONT_CANDIDATES_BOLD, 44)
    f_name = load_font(FONT_CANDIDATES_BOLD, 88)
    f_meta = load_font(FONT_CANDIDATES_REG, 46)
    f_small = load_font(FONT_CANDIDATES_REG, 36)

    # Brand label + accent rule
    d.text((W / 2, 150), BRAND_LABEL, font=f_label, fill=accent, anchor="mm")
    d.rectangle([W / 2 - 120, 195, W / 2 + 120, 201], fill=accent)

    # Exercise name (wrapped, centered; shrink font until it fits above the card)
    name = exercise["name"].title()
    meta = "TARGET: {}  ·  {}".format(
        exercise["target"].upper(), exercise["equipment"].upper()
    )
    for size in (88, 76, 64, 54):
        f_name = load_font(FONT_CANDIDATES_BOLD, size)
        lines = wrap_text(d, name, f_name, W - 160)
        line_h = int(size * 1.2)
        meta_y = 260 + len(lines) * line_h + 30
        if len(lines) <= 4 and meta_y + 60 <= CARD_Y:
            break
    y = 260
    for ln in lines:
        d.text((W / 2, y), ln, font=f_name, fill="#FFFFFF", anchor="ma")
        y += line_h

    # Meta line
    d.text((W / 2, meta_y), meta, font=f_meta, fill=accent, anchor="ma")

    # GIF frame card (the GIF is composited here by ffmpeg — keep coords in sync)
    d.rounded_rectangle(
        [CARD_X, CARD_Y, CARD_X + CARD_SIZE, CARD_Y + CARD_SIZE],
        radius=CARD_RADIUS,
        fill=CARD_COLOR,
        outline=accent,
        width=6,
    )

    # Attribution — REQUIRED by the media license (NOTICE.md). Never remove.
    # Placed just under the card so MPT's bottom subtitles don't cover it.
    d.text(
        (W / 2, CARD_Y + CARD_SIZE + 70),
        exercise["attribution"],
        font=f_small,
        fill="#8E8E96",
        anchor="mm",
    )

    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    img.save(out_png)
    return out_png


# --------------------------------------------------------------------------
# 2. Material MP4 (ffmpeg composite)
# --------------------------------------------------------------------------


def gif_overlay_xy(gif_size):
    x = (W - gif_size) // 2
    y = CARD_Y + (CARD_SIZE - gif_size) // 2
    return x, y


def render_material(exercise, out_mp4, ffmpeg, duration, gif_size, workdir):
    bg_png = os.path.join(workdir, "card.png")
    render_card(exercise, bg_png)
    gif = os.path.join(REPO_ROOT, exercise["gif_url"])
    if not os.path.exists(gif):
        raise FileNotFoundError("missing media: " + gif)
    ox, oy = gif_overlay_xy(gif_size)
    filt = (
        "[1:v]scale={s}:{s}:flags=lanczos,setsar=1[g];"
        "[0:v][g]overlay={x}:{y}:format=auto,format=yuv420p"
    ).format(s=gif_size, x=ox, y=oy)
    cmd = [
        ffmpeg, "-y",
        "-i", bg_png,
        "-stream_loop", "-1", "-i", gif,
        "-filter_complex", filt,
        "-t", str(duration),
        "-r", "30",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart",
        "-an",
        out_mp4,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_mp4


# --------------------------------------------------------------------------
# 3. Narration script
# --------------------------------------------------------------------------


def build_script(exercise, lang, max_steps):
    steps = exercise["instruction_steps"][lang][:max_steps]
    name = exercise["name"]
    parts = [HOOKS[lang].format(name=name)]
    for i, step in enumerate(steps, 1):
        label = STEP_LABELS[lang].format(n=i)
        text = step.rstrip(".")
        if not text.endswith(("。", "！", "？", "!", "?")):
            text += "."
        parts.append("{}: {}".format(label, text))
    parts.append(
        CLOSERS[lang].format(
            target=exercise["target"], equipment=exercise["equipment"]
        )
    )
    return " ".join(parts)


# --------------------------------------------------------------------------
# 4. MoneyPrinterTurbo payload  (POST {mpt_url}/api/v1/videos)
#    Schema: app/models/schema.py VideoParams. video_source="local" requires
#    material paths inside MPT's storage/local_videos directory.
# --------------------------------------------------------------------------


def build_payload(exercise, lang, script, material_url, duration, voice):
    return {
        "video_subject": "{} — form check ({})".format(exercise["name"], lang),
        "video_script": script,
        "video_terms": None,
        "video_aspect": "9:16",
        "video_concat_mode": "sequential",
        "video_transition_mode": None,
        "video_clip_duration": duration,
        "video_count": 1,
        "video_source": "local",
        "video_materials": [
            {"provider": "local", "url": material_url, "duration": duration}
        ],
        "custom_audio_file": None,
        "video_language": lang,
        "voice_name": voice or VOICES[lang],
        "voice_volume": 1.0,
        "voice_rate": 1.0,
        "bgm_type": "random",
        "bgm_file": "",
        "bgm_volume": 0.2,
        "subtitle_enabled": True,
        "subtitle_position": "bottom",
        "custom_position": 70.0,
        "font_name": "STHeitiMedium.ttc",
        "text_fore_color": "#FFFFFF",
        "text_background_color": True,
        "font_size": 60,
        "stroke_color": "#000000",
        "stroke_width": 1.5,
        "n_threads": 2,
        "paragraph_number": 1,
    }


# --------------------------------------------------------------------------
# 5. MPT client (stdlib HTTP)
# --------------------------------------------------------------------------


def mpt_post_video(mpt_url, payload):
    req = urllib.request.Request(
        mpt_url.rstrip("/") + "/api/v1/videos",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode("utf-8"))
    return body["data"]["task_id"]


def mpt_poll_task(mpt_url, task_id, interval=10, timeout=1800):
    url = mpt_url.rstrip("/") + "/api/v1/tasks/" + task_id
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        data = body.get("data") or {}
        if data.get("state") == 1:
            return data
        if data.get("state") == -1:
            raise RuntimeError("MPT task failed: " + json.dumps(data))
        time.sleep(interval)
    raise TimeoutError("MPT task did not finish in time: " + task_id)


def mpt_absolute_url(mpt_url, url):
    """MPT may return relative video paths (/tasks/<id>/final-1.mp4)."""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return mpt_url.rstrip("/") + "/" + url.lstrip("/")


def download(url, out_path):
    with urllib.request.urlopen(url, timeout=300) as r, open(out_path, "wb") as f:
        shutil.copyfileobj(r, f)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def get_exercise(args):
    exercises = load_exercises(args.data)
    for e in exercises:
        if e["id"] == args.id:
            return e
    sys.exit("exercise id not found: " + args.id)


def out_dir_for(args, exercise, lang):
    return os.path.join(args.out, lang, "{}-{}".format(exercise["id"], slugify(exercise["name"])))


def cmd_card(args):
    e = get_exercise(args)
    out = args.output or os.path.join(out_dir_for(args, e, "card"), "card.png")
    render_card(e, out)
    print(out)


def cmd_material(args):
    e = get_exercise(args)
    workdir = out_dir_for(args, e, "material")
    os.makedirs(workdir, exist_ok=True)
    out = args.output or os.path.join(workdir, "material.mp4")
    render_material(e, out, find_ffmpeg(args.ffmpeg), args.duration, args.gif_scale, workdir)
    print(out)


def cmd_script(args):
    e = get_exercise(args)
    for lang in args.lang.split(","):
        lang = lang.strip()
        print("=== {} ===".format(lang))
        print(build_script(e, lang, args.max_steps))
        print()


def run_one(args, exercise, lang, ffmpeg):
    """Render material + script + payload for one (exercise, lang). Returns job dir."""
    job_dir = out_dir_for(args, exercise, lang)
    os.makedirs(job_dir, exist_ok=True)

    script = build_script(exercise, lang, args.max_steps)
    with open(os.path.join(job_dir, "script.txt"), "w", encoding="utf-8") as f:
        f.write(script + "\n")

    material_mp4 = os.path.join(job_dir, "material.mp4")
    if not os.path.exists(material_mp4) or args.force:
        render_material(exercise, material_mp4, ffmpeg, args.duration, args.gif_scale, job_dir)

    # Where MPT will see the material: <mpt_storage>/local_videos/<material_url>
    material_url = os.path.join("reelgen", lang, exercise["id"] + ".mp4")
    if args.mpt_storage:
        dst = os.path.join(args.mpt_storage, "local_videos", material_url)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(material_mp4, dst)

    payload = build_payload(exercise, lang, script, material_url, args.duration, args.voice)
    with open(os.path.join(job_dir, "payload.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return job_dir, payload


def cmd_batch(args):
    exercises = select_exercises(load_exercises(args.data), args)
    if not exercises:
        sys.exit("no exercises matched the given filters")
    langs = [l.strip() for l in args.lang.split(",")]
    ffmpeg = find_ffmpeg(args.ffmpeg)
    if args.send and not args.mpt_storage:
        sys.exit("--send requires --mpt-storage pointing at your MoneyPrinterTurbo "
                 "storage/ dir (materials must live under storage/local_videos)")

    total = len(exercises) * len(langs)
    print("batch: {} exercise(s) x {} language(s) = {} job(s)".format(
        len(exercises), len(langs), total))
    n = 0
    for e in exercises:
        for lang in langs:
            n += 1
            try:
                job_dir, payload = run_one(args, e, lang, ffmpeg)
            except Exception as exc:
                print("[{}/{}] {} {} FAILED: {}".format(n, total, e["id"], lang, exc))
                continue
            print("[{}/{}] {} {} -> {}".format(n, total, e["id"], lang, job_dir))
            if args.send:
                task_id = mpt_post_video(args.mpt_url, payload)
                print("    MPT task: " + task_id)
                if args.wait:
                    data = mpt_poll_task(args.mpt_url, task_id)
                    videos = data.get("videos") or []
                    if videos:
                        final = os.path.join(job_dir, "final.mp4")
                        download(mpt_absolute_url(args.mpt_url, videos[0]), final)
                        print("    final reel: " + final)


def build_parser():
    p = argparse.ArgumentParser(
        description="Generate form-check reels from the exercises dataset "
                    "(optionally via a local MoneyPrinterTurbo instance)."
    )
    p.add_argument("--data", default=DEFAULT_DATA, help="path to exercises.json")
    p.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    p.add_argument("--ffmpeg", default=None, help="path to ffmpeg binary")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("card", help="render the branded canvas PNG for one exercise")
    c.add_argument("--id", required=True)
    c.add_argument("--output", default=None)
    c.set_defaults(func=cmd_card)

    m = sub.add_parser("material", help="render the 1080x1920 material MP4 for one exercise")
    m.add_argument("--id", required=True)
    m.add_argument("--output", default=None)
    m.add_argument("--duration", type=int, default=20, help="material length in seconds")
    m.add_argument("--gif-scale", dest="gif_scale", type=int, default=GIF_SIZE_DEFAULT,
                   help="GIF display size in px (source is 180px; larger = display "
                        "upscale. For full-res media buy a license from Gym visual)")
    m.set_defaults(func=cmd_material)

    s = sub.add_parser("script", help="print the narration script for one exercise")
    s.add_argument("--id", required=True)
    s.add_argument("--lang", default="en", help="comma-separated language codes")
    s.add_argument("--max-steps", dest="max_steps", type=int, default=5)
    s.set_defaults(func=cmd_script)

    b = sub.add_parser("batch", help="render material+script+payload for many exercises")
    b.add_argument("--ids", default=None, help="comma-separated exercise ids")
    b.add_argument("--body-part", dest="body_part", default=None)
    b.add_argument("--equipment", default=None)
    b.add_argument("--limit", type=int, default=None)
    b.add_argument("--lang", default="en", help="comma-separated language codes")
    b.add_argument("--max-steps", dest="max_steps", type=int, default=5)
    b.add_argument("--duration", type=int, default=20)
    b.add_argument("--gif-scale", dest="gif_scale", type=int, default=GIF_SIZE_DEFAULT)
    b.add_argument("--voice", default=None, help="override TTS voice for all languages")
    b.add_argument("--force", action="store_true", help="re-render existing materials")
    b.add_argument("--send", action="store_true", help="POST payloads to MoneyPrinterTurbo")
    b.add_argument("--wait", action="store_true", help="poll tasks and download final reels")
    b.add_argument("--mpt-url", dest="mpt_url", default="http://127.0.0.1:8080")
    b.add_argument("--mpt-storage", dest="mpt_storage", default=None,
                   help="path to MoneyPrinterTurbo's storage/ directory")
    b.set_defaults(func=cmd_batch)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
