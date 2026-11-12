# Festival Video Studio

Create original Hindi festival explainers with research notes, original illustrations, narration, captions, background music, and a thumbnail.

## What it does

- Gemini researches the festival with Google Search grounding when available. If grounding quota is exhausted, the workflow uses key-free DuckDuckGo/Bing search and opens the source pages, then asks Gemini for the script without the Search tool. It does not collect YouTube transcripts.
- Scene illustrations and the thumbnail try DeepAI's public image-generator page first using Playwright and Chromium. If DeepAI is unavailable, blocked, or rate-limited, generation falls back to configured Cloudflare FLUX, Hugging Face FLUX, and Pollinations providers. The automation uses the page's normal prompt and Generate controls and does not bypass sign-in, CAPTCHA, or rate-limit protections.
- **Video overlays:** a sliding chapter-title banner at the start of every scene and a key-fact callout card (label, one Hindi fact, source website) that slides in mid-scene, on top of captions, waveform and progress line.
- Requires at least two grounded web citations and records all source links in a research report.
- Generates an original 9–12 chapter Hindi script from Gemini-grounded research; no source-video captions are collected.
- Verifies the synthesized narration lasts at least six minutes before rendering.
- Produces an MP4, a 1280×720 thumbnail with a prominent topic-specific Hindi headline, metadata JSON, and a research JSON report.
- Generates a new composed illustration for at least every five seconds of narration, with slow pan/zoom, animated voice waveform, word-highlighted captions, and a moving progress line.
- Can schedule a video for **public release on YouTube**; YouTube holds future-scheduled uploads privately until the publish time.

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

## Daily calendar-driven publishing

The researched calendar at `data/india-festival-video-calendar-2026.json` contains one sourced video brief for every date from November 11 through December 31, 2026. The daily Google Apps Script runs near 02:05 IST and checks the featured observance three days ahead. It dispatches only entries with a named festival (not evergreen culture topics), passes the observance date to the workflow, and schedules public release at 09:00 IST two days before that date. This gives the workflow about a day to research, render, and upload before publication. Apps Script triggers run near the selected minute, not at an exact second; the script skips dispatch after 08:00 IST.

To enable the daily trigger:

1. Copy `scheduler/google_apps_script.gs` into a new project at [script.google.com](https://script.google.com).
2. In **Project Settings → Script properties**, add `GITHUB_PAT` with a GitHub token that can dispatch Actions in this repository (`repo` and `workflow` permissions for a classic token).
3. Run `setupDailyTrigger()` once and authorize the requested permissions. Check the Apps Script **Executions** page for dispatch errors.
4. Ensure the repository has `GEMINI_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN` Actions secrets. The YouTube refresh token needs `youtube.upload` and `youtube.readonly` scopes.

The workflow receives the festival date, its calendar topic, and researched source notes, writes the script, renders a video and thumbnail, and uploads it with a 09:00 IST `publishAt` two days before the observance. The thumbnail displays Gemini's short Hindi thumbnail headline in a high-contrast, outlined panel; the generated artwork is prompted to leave negative space for that text. YouTube requires a scheduled video to be uploaded as private; YouTube automatically changes it to public at the scheduled time. Configure the channel's default upload settings and audience/restrictions in YouTube Studio as needed.

## GitHub Actions

The manual workflow runs on a GitHub-hosted Ubuntu runner and installs Chromium for DeepAI image generation. It uses Gemini Google Search grounding when quota is available; on explicit grounding quota exhaustion it falls back to key-free DuckDuckGo/Bing search, opens source pages, and uses standard Gemini generation with those excerpts. The report records the source links and research method. No YouTube transcripts are collected.

Add `GEMINI_API_KEY` and `GEMINI_API_KEY1` (optional backup) plus the existing YouTube OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN`) as repository Actions secrets. Gemini research tries stable Flash models and Flash-Lite fallbacks, then the backup key; temporary rate limits and server errors are retried. Explicitly exhausted Google Search grounding quota switches to key-free web search rather than waiting through retries. GitHub Actions does not inject Cloudflare credentials, avoiding accidental use of its potentially metered image API; it tries the public DeepAI page, Hugging Face FLUX, and Pollinations, then uses designed title cards if image services are unavailable. These public services can still rate-limit or change availability, and Gemini standard generation still requires available Gemini API quota. For scheduled uploads, the refresh token needs both `youtube.upload` and `youtube.readonly` (read access is used to check for duplicate titles). Run **Festival explainer video** manually with a topic, festival date, **publish date (YYYY-MM-DD)**, and **publish time (24-hour HH:MM IST)**. Upload is disabled by default for manual workflow runs; enable it to schedule public release.

On HTTP 429 `RESOURCE_EXHAUSTED`, check the Gemini API quota and billing for the Google Cloud projects behind both configured keys; adding another key from the same project may not add quota. On HTTP 403 stating that the Gemini API free tier is unavailable for the project, enable billing for the Google Cloud project associated with that key or use a key from a project that has Gemini API access. A different Gmail address alone does not guarantee a separate eligible API project or free-tier quota.

## Tests

```powershell
python -m unittest discover -s tests -v
```
