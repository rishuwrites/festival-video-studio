# Festival Video Studio

Create original Hindi festival explainers with research notes, original illustrations, narration, captions, background music, and a thumbnail.

## What it does

- Can analyze public Hindi/English captions from **five distinct YouTube channels** when transcript research is enabled and captions are accessible.
- Uses current Google Search-grounded research; GitHub-hosted workflow uses this mode because YouTube may block caption requests from hosted-runner IPs.
- **Web search research (default):** searches the web for several *types* of websites (panchang/date, reference, government/temple, UP-Bihar regional customs, Hindi news), opens the pages, then Gemini writes research notes from only those pages, and a second Gemini call writes the script from the notes. Tries the Brave Search API when `BRAVE_API_KEY` is set, then DuckDuckGo and Bing (no key). If search fails it falls back to Gemini Google Search grounding. Set `FESTIVAL_WEB_SEARCH=false` to disable; an explicit `research_context` input always wins.
- **Video overlays:** a sliding chapter-title banner at the start of every scene and a key-fact callout card (label, one Hindi fact, source website) that slides in mid-scene, on top of captions, waveform and progress line.
- Requires at least two grounded web citations and records all source links in a research report.
- Generates an original 9–12 chapter Hindi script. Source captions are research inputs only: they are never saved in the report or copied into the script.
- Verifies the synthesized narration lasts at least six minutes before rendering.
- Produces an MP4, thumbnail, metadata JSON, and a research JSON report.
- Generates a new composed illustration for at least every eight seconds of narration, with slow pan/zoom, animated voice waveform, word-highlighted captions, and a moving progress line.
- Can upload directly to YouTube as a **private scheduled video** when YouTube upload is enabled in the manual workflow.

The default coverage is **all of India**, with extra research attention to **Uttar Pradesh and Bihar**, including regional customs. The script must separate nationwide facts from regional practices rather than presenting one state’s customs as universal. Exact muhurta timings vary city by city, so the nationwide video will not present one city’s time as valid across India.

## Run locally

Install Python dependencies and FFmpeg. On Windows, install a Devanagari font such as Nirmala UI. Set API keys in the shell; do not commit them:

```powershell
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "..."
$env:YT_CLIENT_ID = "..."
$env:YT_CLIENT_SECRET = "..."
$env:YT_REFRESH_TOKEN = "..."
python recap\festival_main.py --topic "Dhanteras" --date "2026"
```

YouTube search and uploads use your OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`). Without `YT_API_KEY`, the refresh token must include `youtube.readonly` as well as `youtube.upload`; YouTube Data API v3 must be enabled for the Google Cloud project. Alternatively, add a restricted `YT_API_KEY` Actions secret for public video search; OAuth still needs `youtube.upload` for publishing. Use `--scope` to customize coverage, or the older `--location` option as an alias. For example, `--scope "India (nationwide, focus on UP and Bihar)"`. Image generation can use Cloudflare credentials; the configured image providers are tried as fallbacks. Output is written to `output\`.

## GitHub Actions

The manual workflow runs on a GitHub-hosted Ubuntu runner. Since YouTube blocks caption retrieval from some hosted-runner IPs, Actions uses web-only research without transcript fetching. Normally Gemini's Google Search grounding gathers sources and generates the script in one request. To separate those steps, provide the optional `research_context` workflow input as JSON containing researched `notes`, at least two titled HTTPS `sources`, and optional `search_queries`; the script is then generated with a plain Gemini JSON request, without the Google Search tool. The generated research report marks this as `web_research_only` and must not claim that it analyzed video transcripts. Local runs attempt the five-channel caption workflow by default; set `FESTIVAL_TRANSCRIPT_RESEARCH=false` to use web-only research there too.

Add `GEMINI_API_KEY` and `GEMINI_API_KEY1` (optional backup) plus the existing YouTube OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN`) as repository Actions secrets. Gemini research tries the primary key first, then the backup if all available models fail with it. For scheduled uploads, the refresh token needs both `youtube.upload` and `youtube.readonly` (read access is used to check for duplicate titles). YouTube source-search access and `YT_API_KEY` are not needed in hosted web-only research mode. Optionally add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Run **Festival explainer video** manually with a topic, festival date, **publish date (YYYY-MM-DD)**, and **publish time (24-hour HH:MM IST)**. The upload checkbox is on by default and creates a private scheduled video; the selected time must still be at least 15 minutes in the future after rendering finishes. Turn upload off to generate a preview only.

Festival research can use Gemini's Google Search grounding or independently collected web research followed by plain Gemini generation, similar to the serial recap bot. On HTTP 429 `RESOURCE_EXHAUSTED`, check the Gemini API quota and billing for the Google Cloud projects behind both configured keys; adding another key from the same project may not add quota.

## Tests

```powershell
python -m unittest discover -s tests -v
```
