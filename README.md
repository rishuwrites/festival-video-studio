# Festival Video Studio

Create original Hindi festival explainers with research notes, original illustrations, narration, captions, background music, and a thumbnail.

## What it does

- Gemini researches the festival with Google Search grounding through the Gemini API and writes the script in the same request. The workflow does not launch a search browser, scrape search pages, or collect YouTube transcripts.
- Scene illustrations and the thumbnail try DeepAI's public image-generator page first using Playwright and Chromium. If DeepAI is unavailable, blocked, or rate-limited, generation falls back to configured Cloudflare FLUX, Hugging Face FLUX, and Pollinations providers. The automation uses the page's normal prompt and Generate controls and does not bypass sign-in, CAPTCHA, or rate-limit protections.
- **Video overlays:** a sliding chapter-title banner at the start of every scene and a key-fact callout card (label, one Hindi fact, source website) that slides in mid-scene, on top of captions, waveform and progress line.
- Requires at least two grounded web citations and records all source links in a research report.
- Generates an original 9–12 chapter Hindi script from Gemini-grounded research; no source-video captions are collected.
- Verifies the synthesized narration lasts at least six minutes before rendering.
- Produces an MP4, thumbnail, metadata JSON, and a research JSON report.
- Generates a new composed illustration for at least every five seconds of narration, with slow pan/zoom, animated voice waveform, word-highlighted captions, and a moving progress line.
- Can upload directly to YouTube as a **private scheduled video** when YouTube upload is enabled in the manual workflow.

The default coverage is **all of India**, with extra research attention to **Uttar Pradesh and Bihar**, including regional customs. The script must separate nationwide facts from regional practices rather than presenting one state’s customs as universal. Exact muhurta timings vary city by city, so the nationwide video will not present one city’s time as valid across India.

## Run locally

Install Python dependencies, the Playwright Chromium browser, and FFmpeg. On Windows, install a Devanagari font such as Nirmala UI. Set API keys in the shell; do not commit them:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
$env:GEMINI_API_KEY = "..."
$env:YT_CLIENT_ID = "..."
$env:YT_CLIENT_SECRET = "..."
$env:YT_REFRESH_TOKEN = "..."
python recap\festival_main.py --topic "Dhanteras" --date "2026"
```

YouTube uploads use your OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`). Without `YT_API_KEY`, the refresh token must include `youtube.readonly` as well as `youtube.upload`; YouTube Data API v3 must be enabled for the Google Cloud project. Use `--scope` to customize coverage, or the older `--location` option as an alias. For example, `--scope "India (nationwide, focus on UP and Bihar)"`. Add Cloudflare credentials if you want that provider available as a fallback. Output is written to `output\`.

## GitHub Actions

The manual workflow runs on a GitHub-hosted Ubuntu runner and installs Chromium for DeepAI image generation. Gemini's Google Search grounding performs the research and creates the script through `GEMINI_API_KEY`; no separate browser-search or transcript-research step is run. The report records Gemini's grounding citations and marks the research mode as `gemini_google_search_grounded`.

Add `GEMINI_API_KEY` and `GEMINI_API_KEY1` (optional backup) plus the existing YouTube OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN`) as repository Actions secrets. Gemini research tries stable Flash models and Flash-Lite fallbacks, then the backup key; transient 429/5xx errors are retried with increasing delays. This helps recover from temporary model load/rate limits, but cannot bypass a genuinely exhausted project quota. For scheduled uploads, the refresh token needs both `youtube.upload` and `youtube.readonly` (read access is used to check for duplicate titles). Optionally add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` for a fallback image provider. Run **Festival explainer video** manually with a topic, festival date, **publish date (YYYY-MM-DD)**, and **publish time (24-hour HH:MM IST)**. The upload checkbox is on by default and creates a private scheduled video; the selected time must still be at least 15 minutes in the future after rendering finishes. Turn upload off to generate a preview only.

On HTTP 429 `RESOURCE_EXHAUSTED`, check the Gemini API quota and billing for the Google Cloud projects behind both configured keys; adding another key from the same project may not add quota.

## Tests

```powershell
python -m unittest discover -s tests -v
```
