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
RESOURCES_FILE = os.path.join(BASE_DIR, "resources.json")

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

def load_resources():
    if os.path.exists(RESOURCES_FILE):
        try:
            with open(RESOURCES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"entries": [
        {"type":"youtube","name":"כאן 11","url":"https://www.youtube.com/@kan11","desc":"Israeli public broadcaster"},
        {"type":"youtube","name":"N12 חדשות","url":"https://www.youtube.com/@N12News","desc":"Israeli news channel"},
        {"type":"web","name":"הארץ","url":"https://www.haaretz.co.il","desc":"Quality Hebrew journalism"},
        {"type":"web","name":"ויקיפדיה","url":"https://he.wikipedia.org","desc":"Hebrew Wikipedia"},
    ]}

def save_resources(data):
    with open(RESOURCES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ─── ARTICLE FETCH ────────────────────────────────────────────────────────────
def fetch_article_text(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'he,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': 'https://www.google.com/',
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            # Try to detect encoding
            content_type = resp.headers.get('Content-Type', '')
            encoding = 'utf-8'
            if 'charset=' in content_type:
                encoding = content_type.split('charset=')[-1].strip().split(';')[0]
            try:
                html = raw.decode(encoding, errors='replace')
            except Exception:
                html = raw.decode('utf-8', errors='replace')
    except Exception as e:
        # Try with http if https fails
        if url.startswith('https://'):
            return fetch_article_text(url.replace('https://', 'http://', 1))
        raise e

    # Strip HTML tags and extract text
    import html as html_module
    # Remove scripts, styles, nav elements
    import re as re_mod
    html = re_mod.sub(r'<(script|style|nav|header|footer|aside)[^>]*>[\s\S]*?</>', ' ', html, flags=re_mod.IGNORECASE)
    html = re_mod.sub(r'<[^>]+>', ' ', html)
    html = html_module.unescape(html)
    # Clean whitespace
    text = ' '.join(html.split())
    return text

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
    # On Railway use proxy, locally go direct
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        try:
            from youtube_transcript_api.proxies import WebshareProxyConfig
            return YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(
                proxy_username=PROXY_USERNAME,
                proxy_password=PROXY_PASSWORD
            ))
        except Exception:
            pass
    return YouTubeTranscriptApi()

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
CLAUDE_PROMPT_ADVANCED = """You are a Hebrew language teacher helping an advanced-intermediate learner.

From the Hebrew text below, extract 12 words at B2/advanced-intermediate level — words that go beyond everyday Hebrew but appear in news and media. Skip very basic words and hyper-technical jargon.

For each word provide ONE short, simple example sentence (under 10 words in Hebrew).

Return ONLY a valid JSON array, no markdown, no explanation:
[{"word":"מילה","translation":"english (1-4 words)","root":"א-ב-ג or null","partOfSpeech":"noun/verb/adjective/adverb","sentences":[{"hebrew":"משפט קצר.","english":"Short sentence."}]}]

Hebrew text:
"""

CLAUDE_PROMPT_INTERMEDIATE = """You are a Hebrew language teacher helping an intermediate learner.

From the Hebrew text below, extract 12 words at B1/intermediate level — common everyday words that an intermediate learner would be building towards. These should be practical, frequently used words: common verbs, everyday nouns, basic adjectives. Avoid very basic words (A2 level) and avoid advanced/rare words.

For each word provide ONE short, simple everyday sentence (under 8 words in Hebrew) that clearly shows how the word is used.

Return ONLY a valid JSON array, no markdown, no explanation:
[{"word":"מילה","translation":"english (1-4 words)","root":"א-ב-ג or null","partOfSpeech":"noun/verb/adjective/adverb","sentences":[{"hebrew":"משפט קצר.","english":"Short sentence."}]}]

Hebrew text:
"""

CLAUDE_PROMPT = CLAUDE_PROMPT_ADVANCED  # default

WORD_PROMPT = """You are a Hebrew language teacher.

The user has provided a single Hebrew word. Generate ONE short, simple everyday example sentence (under 10 words) using this word. Return it in JSON array format.

Return ONLY a valid JSON array, no markdown, no explanation:
[{"word":"המילה","translation":"english translation","root":"שורש or null","partOfSpeech":"noun/verb/adjective/adverb","sentences":[{"hebrew":"משפט קצר.","english":"Short sentence."}]}]

Hebrew word: 
"""

def repair_and_parse(json_str):
    """Try to parse JSON, and if truncated, repair it."""
    # Clean up common issues
    json_str = json_str.strip()
    # Remove any markdown fences
    json_str = re.sub(r'^```(?:json)?\s*', '', json_str)
    json_str = re.sub(r'\s*```$', '', json_str)
    json_str = json_str.strip()

    # Try direct parse first
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Find the JSON array in the string (may have extra text around it)
    match = re.search(r'\[[\s\S]*\]', json_str)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            json_str = match.group(0)

    # Try truncating to last complete object
    last_brace = json_str.rfind('}')
    if last_brace > 0:
        for closing in ['}]', '} ]', '},\n]']:
            idx = json_str.rfind(closing)
            if idx > 0:
                try:
                    return json.loads(json_str[:idx+len(closing)])
                except Exception:
                    pass
        # Just close after last }
        try:
            return json.loads(json_str[:last_brace+1] + ']')
        except Exception:
            pass

    raise ValueError("Could not parse the response. Please try again.")

def call_claude_word(word, level='advanced'):
    if not API_KEY:
        raise ValueError("No Anthropic API key configured.")
    level_note = "intermediate (B1) level" if level == 'intermediate' else "advanced-intermediate (B2) level"
    prompt = WORD_PROMPT.replace("Generate ONE short", f"This is a {level_note} word. Generate ONE short")
    payload = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": prompt + word}]
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
    if match:
        return repair_and_parse(match.group(0))
    return repair_and_parse(raw)

def call_claude(hebrew_text, level='advanced', exclude=''):
    if not API_KEY:
        raise ValueError("No Anthropic API key configured.")
    prompt = CLAUDE_PROMPT_INTERMEDIATE if level == 'intermediate' else CLAUDE_PROMPT_ADVANCED
    if exclude:
        prompt = prompt.replace('Hebrew text:', 'Do NOT include these already-shown words: ' + exclude + '\n\nHebrew text:')
    payload = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt + hebrew_text[:6000]}]
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

        if parsed.path == "/fetch-article":
            qs = parse_qs(parsed.query)
            url = (qs.get("url") or [None])[0]
            if not url:
                self.send_json(400, {"error": "Missing ?url= parameter"})
                return
            try:
                text = fetch_article_text(url)
                if len(text) < 100:
                    self.send_json(422, {"error": "Not enough text found on this page."})
                    return
                self.send_json(200, {"text": text[:8000], "length": len(text)})
            except Exception as e:
                self.send_json(422, {"error": f"Could not fetch article: {e}"})
            return

        if parsed.path == "/resources":
            self.send_json(200, load_resources())
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
            level = body.get("level", "advanced")
            exclude = body.get("exclude", "")
            try:
                if text.startswith('__WORD__'):
                    word = text[8:].strip()
                    words = call_claude_word(word, level)
                else:
                    words = call_claude(text, level, exclude)
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

        if parsed.path == "/learnedbank/save":
            words = body.get("words", [])
            source = body.get("source", "")
            learned = load_learned()
            existing = {e["word"] for e in learned}
            added = 0
            for w in words:
                if w.get("word") and w["word"] not in existing:
                    w["source"] = source
                    w["date"] = datetime.datetime.now().strftime("%Y-%m-%d")
                    learned.append(w)
                    existing.add(w["word"])
                    added += 1
            save_learned(learned)
            self.send_json(200, {"saved": added, "total": len(learned)})
            return

        if parsed.path == "/learnedbank/delete":
            word = body.get("word", "")
            learned = load_learned()
            learned = [e for e in learned if e.get("word") != word]
            save_learned(learned)
            self.send_json(200, {"total": len(learned)})
            return

        if parsed.path == "/resources/save":
            entries = body.get("entries", [])
            save_resources({"entries": entries})
            self.send_json(200, {"saved": len(entries)})
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

    if not os.environ.get("RAILWAY_ENVIRONMENT"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
