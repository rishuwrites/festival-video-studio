import base64, io, ipaddress, json, os, re, socket, threading, time, urllib.parse, urllib.request, requests
from PIL import Image
import config as S
_last = [0.0]
_original_getaddrinfo = socket.getaddrinfo
_dns_cache = {}
_dns_lock = threading.Lock()
_dns_resolution = threading.local()

def _getaddrinfo_with_doh(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _original_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        if not isinstance(host, str) or not host or family == socket.AF_INET6 or getattr(_dns_resolution, "active", False):
            raise
        with _dns_lock:
            cached = _dns_cache.get(host)
            address = cached[0] if cached and cached[1] > time.monotonic() else None
            if cached and not address:
                _dns_cache.pop(host, None)
            if not address:
                _dns_resolution.active = True
                try:
                    query = urllib.parse.urlencode({"name": host, "type": "A"})
                    request = urllib.request.Request(
                        f"https://dns.google/resolve?{query}",
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    with urllib.request.urlopen(request, timeout=10) as response:
                        answer = json.loads(response.read().decode("utf-8"))
                    for record in answer.get("Answer", []):
                        if record.get("type") == 1:
                            candidate = str(record.get("data", ""))
                            try:
                                if ipaddress.ip_address(candidate).version == 4:
                                    address = candidate
                                    ttl = max(1, min(int(record.get("TTL", 60)), 300))
                                    _dns_cache[host] = (address, time.monotonic() + ttl)
                                    break
                            except ValueError:
                                continue
                finally:
                    _dns_resolution.active = False
        if address:
            return _original_getaddrinfo(address, port, family, type, proto, flags)
        raise

socket.getaddrinfo = _getaddrinfo_with_doh

def _retryable_image_error(exc):
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    message = str(exc).lower()
    if status is None:
        match = re.search(r"\b([45]\d\d)\b", message)
        status = int(match.group(1)) if match else None
    if (status in (400, 401, 402, 403, 404) or "quota" in message or "4006" in message
            or "daily free allocation" in message or "out of credits" in message
            or "insufficient credit" in message or "payment required" in message):
        return False
    return True

def _cloudflare(prompt, seed, attempt=0):
    acc = (os.getenv("CLOUDFLARE_ACCOUNT_ID") or os.getenv("CF_ACCOUNT_ID") or "").strip()
    tok = (os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CF_API_TOKEN") or "").strip()
    if not (acc and tok): return None
    # Request native 16:9 widescreen on first attempts; fallback to default if needed
    payload = {"prompt": prompt[:2000], "steps": 4}
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                      headers={"Authorization": f"Bearer {tok}"}, json=payload, timeout=120)
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("image/"):
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    result = r.json()
    if not result.get("success", True) or "result" not in result:
        raise ValueError(f"Cloudflare returned an unexpected response: {str(result)[:300]}")
    return Image.open(io.BytesIO(base64.b64decode(result["result"]["image"]))).convert("RGB")

def _pollinations(prompt, seed, attempt=0):
    wait = 16 - (time.time() - _last[0])                       # anonymous free tier pacing
    if wait > 0: time.sleep(wait)
    # Rotate across free Pollinations models on retries so a busy model never blocks generation
    models = ["flux", "flux-realism", "turbo"]
    model = models[attempt % len(models)]
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:1500]) +
           f"?width=1280&height=720&seed={(int(seed) + attempt) % 2147483647}&model={model}&nologo=true&enhance=true&safe=true")
    hdr = {"User-Agent": "SerialRecapBot/1.0"}
    if os.getenv("POLLINATIONS_TOKEN"):
        hdr["Authorization"] = "Bearer " + os.getenv("POLLINATIONS_TOKEN")
    r = requests.get(url, headers=hdr, timeout=180); _last[0] = time.time()
    r.raise_for_status()
    if not r.headers.get("content-type", "").startswith("image"):
        raise ValueError("not an image")
    return Image.open(io.BytesIO(r.content)).convert("RGB")

def _flux(prompt, seed, attempt=0):
    from gradio_client import Client

    space = os.getenv("HF_FLUX_SPACE") or "https://black-forest-labs-flux-1-schnell.hf.space"
    result = Client(space, verbose=False).predict(
        prompt=prompt[:2000],
        seed=int(seed) % 2147483647,
        randomize_seed=True,
        width=1280,
        height=720,
        num_inference_steps=4,
        api_name="/infer",
    )
    image_data = result[0] if isinstance(result, (list, tuple)) else result
    if isinstance(image_data, dict):
        image_data = image_data.get("path")
    if isinstance(image_data, Image.Image):
        return image_data.convert("RGB")
    if not isinstance(image_data, (str, os.PathLike)):
        raise ValueError("FLUX returned no image file")
    return Image.open(image_data).convert("RGB")

def generate_thumbnail(prompt, seed, out, style=None):
    """Generate one cover, preferring Cloudflare FLUX then the existing providers."""
    full = f"{prompt}. Style: {style or S.STYLE}"
    providers = (("cloudflare", _cloudflare, 3), ("flux", _flux, 1), ("pollinations", _pollinations, 3))
    for name, fn, attempts in providers:
        for attempt in range(attempts):
            try:
                im = fn(full, seed, attempt=attempt)
                if im is None:
                    break
                if im.width < 400 or im.height < 300:
                    raise ValueError("image is too small")
                im.save(out, quality=92)
                print(f"    thumbnail art ok via {name} (try {attempt + 1})")
                return True
            except Exception as exc:
                print(f"    thumbnail {name} try {attempt + 1}/{attempts}: {type(exc).__name__}: {str(exc)[:80]}")
                if not _retryable_image_error(exc):
                    break
                if attempt + 1 < attempts:
                    rate_limited = getattr(getattr(exc, "response", None), "status_code", None) == 429
                    time.sleep((30 if rate_limited else 6) * (attempt + 1))
    return False

def reuse_nearest_generated_images(comps, generated_indices):
    """Fill scenes without generated art from the nearest scene that has it."""
    sources = sorted(set(generated_indices))
    if not sources:
        return []
    reused = []
    for i in sorted(comps):
        if comps[i]:
            continue
        source = min(sources, key=lambda candidate: (abs(candidate - i), candidate))
        comps[i] = list(comps[source])
        reused.append((i, source))
    return reused

def generate(prompt, seed, out, style=None):
    """Make one illustration, preferring Cloudflare FLUX then the existing providers."""
    full = f"{prompt}. Style: {style or S.STYLE}"
    providers = (("cloudflare", _cloudflare, 3), ("flux", _flux, 1), ("pollinations", _pollinations, 3))
    for name, fn, attempts in providers:
        for attempt in range(attempts):
            try:
                im = fn(full, seed, attempt=attempt)
                if im is None:
                    break
                if im.width < 400 or im.height < 300:
                    raise ValueError("image is too small")
                im.save(out, quality=92)
                print(f"    image ok via {name} (try {attempt + 1})")
                return True
            except Exception as exc:
                print(f"    image {name} try {attempt + 1}/{attempts}: {type(exc).__name__}: {str(exc)[:80]}")
                if not _retryable_image_error(exc):
                    break
                if attempt + 1 < attempts:
                    rate_limited = getattr(getattr(exc, "response", None), "status_code", None) == 429
                    time.sleep((30 if rate_limited else 6) * (attempt + 1))
    return False
