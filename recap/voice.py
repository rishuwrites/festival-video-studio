import asyncio, os, re, subprocess, time
import config as S

# Expressive rate and pitch adjustments per scene emotion (supported natively by edge-tts for free)
_EMO_PROSODY = {
    "hook":     ("+12%", "+2Hz"),
    "cliff":    ("+12%", "+2Hz"),
    "shock":    ("+12%", "+3Hz"),
    "tense":    ("+11%", "+1Hz"),
    "angry":    ("+12%", "+1Hz"),
    "sad":      ("+5%",  "-2Hz"),
    "romantic": ("+8%",  "+1Hz"),
    "happy":    ("+10%", "+2Hz"),
}

def sanitize(t):
    t = t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'").replace("\u2014", ", ").replace("\u2013", ", ").replace("\u2026", ".")
    t = re.sub(r"[^\u0900-\u097F\x20-\x7E\u0964]", " ", t)       # keep Devanagari, ASCII, danda
    return re.sub(r"\s+", " ", t).strip()

async def _edge_stream(text, path, voice_name, rate="+10%", pitch="+0Hz"):
    import edge_tts
    comm = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)
    words = []
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            ctype = chunk.get("type")
            if ctype == "audio":
                f.write(chunk["data"])
            elif ctype == "WordBoundary":
                w_start = chunk.get("offset", 0) / 10_000_000.0
                w_dur = max(chunk.get("duration", 0) / 10_000_000.0, 0.05)
                w_txt = (chunk.get("text") or "").strip()
                if w_txt:
                    words.append((w_txt, w_start, w_start + w_dur))
    return words

def _make_edge_fn(voice_name):
    def _fn(text, path, emo="tense"):
        rate, pitch = _EMO_PROSODY.get(emo, ("+10%", "+0Hz"))
        return asyncio.run(_edge_stream(text, path, voice_name, rate=rate, pitch=pitch))
    _fn.__name__ = f"edge({voice_name})"
    return _fn

def _gtts(text, path, emo="tense"):                 # last-resort free fallback
    from gtts import gTTS
    gTTS(text=text, lang="hi", tld="co.in").save(path)
    return []

def _try(fn, text, path, tries, emo="tense"):
    for i in range(tries):
        try:
            if os.path.exists(path): os.remove(path)
            words = fn(text, path, emo=emo)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return True, (words or [])
        except Exception as e:
            print(f"    {fn.__name__} try {i + 1}/{tries}: {type(e).__name__}: {str(e)[:90]}")
        time.sleep(1.5 * (i + 1))
    return False, []

def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).decode())

def _one(lines, outdir, tag, emo, fn, tries):
    paths, raw_words = [], []
    prosody_key = tag if tag in ("hook", "cliff") else (emo or "tense")
    for i, ln in enumerate(lines):
        p = f"{outdir}/{tag}_{i}.mp3"
        ok, w_list = _try(fn, sanitize(ln), p, tries, emo=prosody_key)
        if not ok: return None
        paths.append(p)
        raw_words.append(w_list)
    times, word_times, t = [], [], 0.0
    for p, w_list in zip(paths, raw_words):
        d = dur(p)
        times.append((t, t + d))
        # Shift word boundary timestamps by the line's start offset `t`
        shifted = [(w, t + ws, min(t + we, t + d)) for (w, ws, we) in w_list]
        word_times.append(shifted)
        t += d
    lst = f"{outdir}/{tag}_a.txt"; open(lst, "w").write("".join(f"file '{os.path.abspath(p)}'\n" for p in paths))
    out = f"{outdir}/{tag}.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "160k", out], check=True)
    return out, times, word_times

def synth_all(segments, outdir):
    """segments: [{'tag','lines','emo'}]. Tries primary neural voice, backup neural voice, then gTTS."""
    primary_voice = S.VOICE or "hi-IN-SwaraNeural"
    backup_voice = "hi-IN-MadhurNeural" if "Swara" in primary_voice else "hi-IN-SwaraNeural"
    engines = [
        (f"edge-tts ({primary_voice})", _make_edge_fn(primary_voice), 4),
        (f"edge-tts ({backup_voice})", _make_edge_fn(backup_voice), 3),
        ("gtts", _gtts, 3),
    ]
    for name, fn, tries in engines:
        res, ok = [], True
        for s in segments:
            r = _one(s["lines"], outdir, s["tag"], s.get("emo", "tense"), fn, tries)
            if r is None:
                print(f"  {name} failed on {s['tag']}; switching engine for the whole video")
                ok = False; break
            res.append(r)
        if ok:
            print("  voice:", name)
            for s, (a, t, wt) in zip(segments, res):
                s["audio"], s["times"], s["word_times"] = a, t, wt
            return
    raise SystemExit("All voice engines failed")
