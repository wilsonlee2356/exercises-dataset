#!/usr/bin/env python3
"""
reelgen web UI — a small local server (Python stdlib only) that wraps
reelgen.py with a browser interface.

    .venv/bin/python tools/reelgen/server.py [--port 8321]

Then open http://127.0.0.1:8321

No web framework: http.server + JSON endpoints + the single-page webui.html.
"""

import argparse
import json
import os
import threading
import traceback
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import reelgen

ROOT = os.path.dirname(os.path.abspath(__file__))
WEBUI_PATH = os.path.join(ROOT, "webui.html")
CACHE_DIR = os.path.join(reelgen.DEFAULT_OUT, ".cache")
OUT_ROOT = os.path.abspath(reelgen.DEFAULT_OUT)

EXERCISES = reelgen.load_exercises(reelgen.DEFAULT_DATA)
BY_ID = {e["id"]: e for e in EXERCISES}

# MPT connection defaults (overridable via environment, used to pre-fill the UI
# and as fallbacks for batch jobs) — in Docker these point at the mpt-api service.
MPT_URL_DEFAULT = os.environ.get("REELGEN_MPT_URL", "http://127.0.0.1:8080")
MPT_STORAGE_DEFAULT = os.environ.get("REELGEN_MPT_STORAGE", "")

JOBS = {}          # job_id -> {"log": [str], "done": bool, "error": str|None, "outputs": [str]}
JOBS_LOCK = threading.Lock()

CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".mp4": "video/mp4",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


def log(job_id, msg):
    with JOBS_LOCK:
        JOBS[job_id]["log"].append(msg)


def run_batch_job(job_id, params):
    """Background worker: mirrors reelgen.cmd_batch but driven by the UI."""
    try:
        ffmpeg = reelgen.find_ffmpeg(params.get("ffmpeg"))
        ids = params["ids"]
        langs = params["langs"]
        duration = int(params.get("duration", 20))
        max_steps = int(params.get("max_steps", 5))
        gif_scale = int(params.get("gif_scale", reelgen.GIF_SIZE_DEFAULT))
        send = bool(params.get("send"))
        wait = bool(params.get("wait"))
        mpt_url = params.get("mpt_url") or MPT_URL_DEFAULT
        mpt_storage = params.get("mpt_storage") or MPT_STORAGE_DEFAULT

        if send and not mpt_storage:
            raise ValueError("MPT storage path is required when 'send to MPT' is enabled "
                             "(materials must live under <MPT>/storage/local_videos)")

        total = len(ids) * len(langs)
        log(job_id, "batch: {} exercise(s) x {} language(s) = {} job(s)".format(
            len(ids), len(langs), total))
        n = 0
        for ex_id in ids:
            e = BY_ID.get(ex_id)
            if not e:
                log(job_id, "  {} skipped (unknown id)".format(ex_id))
                continue
            for lang in langs:
                n += 1
                job_dir = reelgen.out_dir_for(
                    argparse.Namespace(out=reelgen.DEFAULT_OUT), e, lang)
                os.makedirs(job_dir, exist_ok=True)
                log(job_id, "[{}/{}] {} {}".format(n, total, ex_id, lang))

                script = reelgen.build_script(e, lang, max_steps)
                with open(os.path.join(job_dir, "script.txt"), "w", encoding="utf-8") as f:
                    f.write(script + "\n")

                material_mp4 = os.path.join(job_dir, "material.mp4")
                reelgen.render_material(e, material_mp4, ffmpeg, duration, gif_scale, job_dir)
                log(job_id, "    material + script rendered")

                material_url = os.path.join("reelgen", lang, ex_id + ".mp4")
                if mpt_storage:
                    import shutil
                    dst = os.path.join(mpt_storage, "local_videos", material_url)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copyfile(material_mp4, dst)

                payload = reelgen.build_payload(
                    e, lang, script, material_url, duration, params.get("voice") or None)
                with open(os.path.join(job_dir, "payload.json"), "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)

                if send:
                    task_id = reelgen.mpt_post_video(mpt_url, payload)
                    log(job_id, "    MPT task: " + task_id)
                    if wait:
                        data = reelgen.mpt_poll_task(mpt_url, task_id)
                        videos = data.get("videos") or []
                        if videos:
                            final = os.path.join(job_dir, "final.mp4")
                            reelgen.download(reelgen.mpt_absolute_url(mpt_url, videos[0]), final)
                            rel = os.path.relpath(final, OUT_ROOT)
                            with JOBS_LOCK:
                                JOBS[job_id]["outputs"].append(rel)
                            log(job_id, "    final reel: " + rel)
        log(job_id, "done.")
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id]["error"] = "{}: {}".format(type(exc).__name__, exc)
            JOBS[job_id]["log"].append(traceback.format_exc())
    finally:
        with JOBS_LOCK:
            JOBS[job_id]["done"] = True


class Handler(BaseHTTPRequestHandler):
    server_version = "reelgen-ui/1.0"

    # -- helpers ----------------------------------------------------------

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json")

    def _file(self, path, ctype=None):
        if not os.path.isfile(path):
            self._send(404, "not found")
            return
        ctype = ctype or CTYPES.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def log_message(self, fmt, *args):  # quieter console
        pass

    # -- routing ----------------------------------------------------------

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, q = url.path, urllib.parse.parse_qs(url.query)

        if path == "/":
            self._file(WEBUI_PATH)
        elif path == "/api/options":
            self._json({
                "langs": reelgen.LANGS,
                "body_parts": sorted({e["body_part"] for e in EXERCISES}),
                "equipment": sorted({e["equipment"] for e in EXERCISES}),
                "count": len(EXERCISES),
                "mpt_url": MPT_URL_DEFAULT,
                "mpt_storage": MPT_STORAGE_DEFAULT,
            })
        elif path == "/api/exercises":
            rows = EXERCISES
            bp, eq = q.get("body_part", [""])[0], q.get("equipment", [""])[0]
            query = q.get("q", [""])[0].strip().lower()
            if bp:
                rows = [e for e in rows if e["body_part"] == bp]
            if eq:
                rows = [e for e in rows if e["equipment"] == eq]
            if query:
                rows = [e for e in rows if query in e["name"] or query in e["id"]]
            self._json({
                "total": len(rows),
                "items": [
                    {"id": e["id"], "name": e["name"], "body_part": e["body_part"],
                     "equipment": e["equipment"], "target": e["target"]}
                    for e in rows[:200]
                ],
            })
        elif path.startswith("/api/card/"):
            ex_id = os.path.basename(path).replace(".png", "")
            e = BY_ID.get(ex_id)
            if not e:
                self._send(404, "unknown id")
                return
            cached = os.path.join(CACHE_DIR, "card", ex_id + ".png")
            if not os.path.exists(cached):
                reelgen.render_card(e, cached)
            self._file(cached, "image/png")
        elif path == "/api/script":
            e = BY_ID.get(q.get("id", [""])[0])
            lang = q.get("lang", ["en"])[0]
            if not e or lang not in reelgen.LANGS:
                self._send(400, "bad id or lang")
                return
            max_steps = int(q.get("max_steps", ["5"])[0])
            self._json({"lang": lang, "script": reelgen.build_script(e, lang, max_steps)})
        elif path == "/api/material":
            e = BY_ID.get(q.get("id", [""])[0])
            if not e:
                self._send(404, "unknown id")
                return
            duration = min(int(q.get("duration", ["6"])[0]), 60)
            cached = os.path.join(CACHE_DIR, "material", "{}-{}s.mp4".format(e["id"], duration))
            if not os.path.exists(cached):
                os.makedirs(os.path.dirname(cached), exist_ok=True)
                reelgen.render_material(e, cached, reelgen.find_ffmpeg(None),
                                        duration, reelgen.GIF_SIZE_DEFAULT,
                                        os.path.dirname(cached))
            self._file(cached, "video/mp4")
        elif path.startswith("/api/jobs/"):
            job_id = os.path.basename(path)
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                self._json(job if job else {"error": "unknown job"}, 200 if job else 404)
        elif path == "/api/mpt/ping":
            mpt_url = q.get("url", ["http://127.0.0.1:8080"])[0].rstrip("/")
            try:
                with urllib.request.urlopen(mpt_url + "/docs", timeout=3) as r:
                    ok = r.status == 200
                self._json({"ok": ok})
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)})
        elif path.startswith("/out/"):
            rel = path[len("/out/"):]
            full = os.path.abspath(os.path.join(OUT_ROOT, rel))
            if not full.startswith(OUT_ROOT):  # no path escape
                self._send(403, "forbidden")
                return
            self._file(full)
        else:
            self._send(404, "not found")

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != "/api/batch":
            self._send(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            params = json.loads(self.rfile.read(length).decode("utf-8"))
            assert params.get("ids") and params.get("langs"), "ids and langs are required"
        except Exception as exc:
            self._json({"error": "bad request: {}".format(exc)}, 400)
            return
        job_id = uuid.uuid4().hex[:8]
        with JOBS_LOCK:
            JOBS[job_id] = {"log": [], "done": False, "error": None, "outputs": []}
        threading.Thread(target=run_batch_job, args=(job_id, params), daemon=True).start()
        self._json({"job_id": job_id})


def main():
    ap = argparse.ArgumentParser(description="reelgen web UI")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (use 0.0.0.0 inside Docker)")
    ap.add_argument("--port", type=int, default=8321)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = "http://127.0.0.1:{}".format(args.port)
    print("reelgen UI → {}  (Ctrl+C to stop)".format(url))
    if not args.no_browser and args.host == "127.0.0.1":
        webbrowser.open(url)
    srv.serve_forever()


if __name__ == "__main__":
    main()
