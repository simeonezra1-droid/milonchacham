#!/usr/bin/env python3
"""
מילון חכם – Local Backend Server
Run: py server.py
"""

import json, os, re, threading, webbrowser, urllib.request, urllib.error, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    print("\n❌  Missing dependency. Please run:\n\n    py -m pip install youtube-transcript-api\n")
    raise SystemExit(1)

PORT = int(os.environ.get('PORT', 7779))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, "milonchacham.html")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
WORDBANK_FILE = os.path.join(BASE_DIR, "wordbank.json")
LEARNED_FILE = os.path.join(BASE_DIR, "learned.json")

# ─── API KEY ──────────────────────────────────────────────────────────────────
def load_api_key():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                if cfg.get("ANTHROPIC_API_KEY"):
                    return cfg["ANTHROPIC_API_KEY"]
        except Exception:
            pass
    return os.environ.get("ANTHROPIC_API_KEY", "")

def save_api_key(key):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"ANTHROPIC_API_KEY": key}, f)

API_KEY = load_api_key()
if not API_KEY:
    print("\n⚠️  No ANTHROPIC_API_KEY found. Set it as an environment variable.\n")

# ─── WORD BANK ────────────────────────────────────────────────────────────────
def load_wordbank():
    if os.path.exists(WORDBANK_FILE):
        try:
            with open(WORDBANK_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_wordbank(entries):
    with open(WORDBANK_FILE, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

def load_learned():
    if os.path.exists(LEARNED_FILE):
        try:
            with open(LEARNED_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_learned(entries):
    with open(LEARNED_FILE, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

# ─── YOUTUBE ──────────────────────────────────────────────────────────────────
def extract_video_id(url_or_id):
    s = url_or_id.strip()
    if re.match(r'^[A-Za-z0-9_-]{11}$', s):
        return s
    parsed = urlparse(s)
    if parsed.hostname and 'youtu.be' in parsed.hostname:
        return parsed.path.lstrip('/').split('?')[0]
    if parsed.hostname and 'youtube.com' in parsed.hostname:
        qs = parse_qs(parsed.query)
        if 'v' in qs:
            return qs['v'][0]
    raise ValueError(f"Cannot extract video ID from: {s!r}")

PROXY_USERNAME = os.environ.get('WEBSHARE_USER', 'euxsvndg')
PROXY_PASSWORD = os.environ.get('WEBSHARE_PASS', 'y8o5s8o3jesk')
PROXY_URL = f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@p.webshare.io:80"

def make_api():
    from youtube_transcript_api.proxies import WebshareProxyConfig
    try:
        return YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(
            proxy_username=PROXY_USERNAME,
            proxy_password=PROXY_PASSWORD
        ))
    except Exception:
        # Fall back to direct if proxy config not supported
        proxies = {"http": PROXY_URL, "https": PROXY_URL}
        return YouTubeTranscriptApi(proxies=proxies)

def get_hebrew_transcript(video_id):
    try:
        api = make_api()
    except Exception:
        api = YouTubeTranscriptApi()

    for lang_code in ('he', 'iw'):
        try:
            fetched = api.fetch(video_id, languages=[lang_code])
            text = " ".join(s.text for s in fetched if s.text)
            if text.strip():
                return {"transcript": text, "language": "Hebrew", "video_id": video_id}
        except Exception:
            pass
    try:
        transcript_list = api.list(video_id)
        for t in transcript_list:
            if t.language_code in ('he', 'iw'):
                fetched = t.fetch()
                text = " ".join(s.text for s in fetched if s.text)
                if text.strip():
                    return {"transcript": text, "language": t.language, "video_id": video_id}
        for t in transcript_list:
            try:
                translated = t.translate('he')
                fetched = translated.fetch()
                text = " ".join(s.text for s in fetched if s.text)
                if text.strip():
                    return {"transcript": text, "language": f"Translated from {t.language}", "video_id": video_id}
            except Exception:
                pass
        return {"error": "No Hebrew subtitles found.\nTry a video from כאן 11, N12, or other Israeli news channels."}
    except Exception as e:
        err = str(e)
        if "disabled" in err.lower():
            return {"error": "Subtitles are disabled for this video."}
        return {"error": f"Could not fetch transcript: {err}"}

# ─── CLAUDE ───────────────────────────────────────────────────────────────────
CLAUDE_PROMPT = """You are a Hebrew language teacher helping an advanced-intermediate learner.

From the Hebrew text below, extract 8-12 words at B2/advanced-intermediate level — words a learner who knows everyday Hebrew might not know yet, but would encounter in news or media. Skip very basic words and hyper-technical jargon.

Return ONLY a valid JSON array, no markdown, no explanation:
[{"word":"מילה","translation":"english (1-4 words)","root":"א-ב-ג or null","partOfSpeech":"noun/verb/adjective/adverb","sentences":[{"hebrew":"משפט פשוט.","english":"Simple sentence."},{"hebrew":"משפט שני.","english":"Second sentence."}]}]

Hebrew text:
"""

def call_claude(hebrew_text):
    if not API_KEY:
        raise ValueError("No Anthropic API key configured.")
    payload = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": CLAUDE_PROMPT + hebrew_text[:6000]}]
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    raw = "".join(b.get("text","") for b in data.get("content",[]) if b.get("type")=="text")
    match = re.search(r'\[[\s\S]*\]', raw)
    if not match:
        raise ValueError("No JSON found in Claude response")
    return json.loads(match.group(0))

# ─── HTTP SERVER ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  → {self.command} {self.path}  [{args[1]}]")

    def send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, code, content):
        body = content if isinstance(content, bytes) else content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path in ('/', '/app', '/milonchacham.html'):
            if os.path.exists(HTML_FILE):
                with open(HTML_FILE, 'rb') as f:
                    self.send_html(200, f.read())
            else:
                self.send_html(404, "<h1>milonchacham.html not found</h1>")
            return

        if parsed.path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        if parsed.path == "/transcript":
            qs = parse_qs(parsed.query)
            raw = (qs.get("url") or qs.get("v") or [None])[0]
            if not raw:
                self.send_json(400, {"error": "Missing ?url= parameter"})
                return
            try:
                video_id = extract_video_id(raw)
            except ValueError as e:
                self.send_json(400, {"error": str(e)})
                return
            print(f"  📹 Fetching transcript: {video_id}")
            result = get_hebrew_transcript(video_id)
            self.send_json(200 if "transcript" in result else 422, result)
            return

        if parsed.path == "/wordbank":
            self.send_json(200, {"entries": load_wordbank()})
            return

        if parsed.path == "/learnedbank":
            self.send_json(200, {"entries": load_learned()})
            return

        self.send_json(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))

        if parsed.path == "/analyze":
            text = body.get("text", "")
            if not text.strip():
                self.send_json(400, {"error": "No text provided"})
                return
            print(f"  🧠 Analyzing {len(text)} chars with Claude...")
            try:
                words = call_claude(text)
                self.send_json(200, {"words": words})
            except Exception as e:
                self.send_json(500, {"error": f"Claude API error: {e}"})
            return

        if parsed.path == "/wordbank/save":
            # Expects: { words: [...], source: "..." }
            words = body.get("words", [])
            source = body.get("source", "")
            if not words:
                self.send_json(400, {"error": "No words provided"})
                return
            bank = load_wordbank()
            if len(bank) >= 4:
                self.send_json(200, {"saved": 0, "total": len(bank), "full": True})
                return
            existing_words = {e["word"] for e in bank}
            added = 0
            for w in words:
                if len(bank) >= 4:
                    break
                if w.get("word") and w["word"] not in existing_words:
                    w["source"] = source
                    w["date"] = datetime.datetime.now().strftime("%Y-%m-%d")
                    bank.append(w)
                    existing_words.add(w["word"])
                    added += 1
            save_wordbank(bank)
            print(f"  💾 Saved {added} new words to word bank ({len(bank)} total)")
            self.send_json(200, {"saved": added, "total": len(bank)})
            return

        if parsed.path == "/wordbank/delete":
            word = body.get("word", "")
            bank = load_wordbank()
            bank = [e for e in bank if e.get("word") != word]
            save_wordbank(bank)
            self.send_json(200, {"total": len(bank)})
            return

        self.send_json(404, {"error": "Unknown endpoint"})


if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════╗
║     מילון חכם  –  Local Server           ║
║     http://localhost:{PORT}               ║
╚══════════════════════════════════════════╝
  Press Ctrl+C to stop.
""")
    httpd = HTTPServer(("0.0.0.0", PORT), Handler)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
