# Festival Video Studio

Create original Hindi festival explainers with research notes, original illustrations, narration, captions, background music, and a thumbnail.

## What it does

- Gemini researches the festival with Google Search grounding when available. If grounding quota is exhausted, the workflow uses key-free DuckDuckGo/Bing search and opens the source pages, then asks Gemini for the script without the Search tool. It does not collect YouTube transcripts.
- Scene illustrations and the thumbnail try DeepAI's public image-generator page first using Playwright and Chromium. If DeepAI is unavailable, blocked, or rate-limited, generation falls back to configured Cloudflare FLUX, Hugging Face FLUX, and Pollinations providers. The automation uses the page's normal prompt and Generate controls and does not bypass sign-in, CAPTCHA, or rate-limit protections.
- **Video overlays:** a sliding chapter-title banner at the start of every scene and a key-fact callout card (label, one Hindi fact, source website) that slides in mid-scene, on top of captions, waveform and progress line.
- Requires at least two grounded web citations and records all source links in a research report.
- Generates an original 9–12 chapter Hindi script from Gemini-grounded research; no source-video captions are collected.
- Verifies the synthesized narration lasts at least six minutes before rendering.
- Produces an MP4, a 1280×720 thumbnail with a prominent Hindi festival name, high-contrast outlined headline, contextual art on the right, and a date badge, plus metadata JSON and a research JSON report.
- Uses a bold Devanagari font with Pillow RAQM shaping for thumbnails; rendering stops with a clear error if correct Hindi shaping is unavailable.
- Builds searchable, source-aware video titles, descriptions, Hindi/English tags, chapter summaries, and relevant hashtags without exceeding YouTube metadata limits.
- Generates a new composed illustration for at least every five seconds of narration, with slow pan/zoom, animated voice waveform, word-highlighted captions, and a moving progress line.
- Can schedule a video for **public release on YouTube and a Facebook Page** at the same date and time.

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

## Daily 10-video long-form publishing

The `daily-batch.yml` workflow plans ten total **16:9 long-form video slots** per calendar date. When the legacy Apps Script has a video for that release date, it owns the 09:00 IST slot and the batch renders the other nine slots. The batch never renders the legacy slot. If no legacy entry exists, the batch fills all ten slots. Batch jobs use `fail-fast: false` and at most three concurrent renders; no Shorts or vertical videos are produced.

The batch workflow is manual-only (`workflow_dispatch`); its GitHub `schedule:` trigger stays commented out. The Apps Script dispatches the batch for a publish date two days ahead and continues dispatching the existing legacy video for the next day's 09:00 release. The two workflows share a publishing concurrency group to avoid overlapping uploads.

Each batch slot writes a result artifact and a GitHub Actions job-summary row showing YouTube success/failure, video ID, and any Drive fallback link. Apps Script checks dispatched publish dates every two hours; after the current workflow finishes, it dispatches a retry matrix for only slots that still have no YouTube video ID. The legacy workflow likewise reports its YouTube result and retries its failed run only. Retries reuse the same title/date/slot and first check the channel for an existing title, treating that existing upload as success rather than uploading a duplicate. Retries stop when the scheduled publish time is within 15 minutes; API quota limits or other platform failures can still prevent a video from being scheduled in time.

`config/channel_focus.json` sets a minimum 80% core festival/culture share, a maximum of one astrology-category video per day, and at most two rashi-encyclopedia episodes per ISO week. The builder fails with a clear error if the planned active topics exceed those limits. Festival and vrat topics without verified dates, and topics duplicated against nearby legacy briefs, are replaced with distinct evergreen core-culture topics, keeping all ten daily slots active.

The calendar covers November 18 through December 31, 2026. Seed owner-editable data and the distinct topic pool with:

```powershell
python calendar\seed_templates.py
```

Before building the calendar:

1. In `data\festival_dates_2026.json`, verify each date against independent published sources, enter the dates and URLs, and change only confirmed entries to `"verified": true`. The initial candidate dates are deliberately unverified. Add the date-specific Ekadashi, Pradosh, Sankashti Chaturthi, Purnima, and Amavasya occurrences from a trusted source.
2. Fill every date in `data\panchang_2026_11_18_to_12_31.csv` with the source-provided `tithi`, `paksha`, `nakshatra`, `moon_rashi`, `rahu_kaal_start`, `rahu_kaal_end`, and `sunrise`. Include the source's city in `source_location` and an HTTPS `source_url` for the daily video because sunrise and Rahu Kaal are location-specific. Do not infer missing values.
3. Generate and commit the files once the source data is complete:

```powershell
python calendar\build_calendar.py --from 2026-11-18 --to 2026-12-31
```

The builder creates `calendar\content_calendar.csv`, `calendar\content_calendar.json`, and `calendar\CALENDAR.md`. It stops on missing daily panchang values, schedules festival/vrat topics only for verified dates, and substitutes evergreen core-culture topics when no verified event fits or a topic conflicts with a nearby legacy brief. A festival less than two days away at the beginning of the range is marked `late_prepublish` and assigned to the earliest calendar date. `PRE_PUBLISH_DAYS_MIN` and `PRE_PUBLISH_DAYS_MAX` may be set to 2 or 3 (in order). The existing YouTube scheduler still rejects publish times less than 15 minutes in the future.

The 06:00 daily panchang/rashifal script reads only the supplied panchang row and `data\rashifal_rules.json`; predictions are fixed, non-certain interpretations, with a disclaimer in the video description. Rashi episodes use the fixed chapter template and the content is framed as traditional astrology. The generated evergreen topic pool contains at least 300 distinct bilingual topics. Rebuilding the calendar retains completed video statuses and IDs.

Set `GEMINI_API_KEY`, optional `GEMINI_API_KEY1`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN` as repository Actions secrets. Every planned video tries YouTube API upload. YouTube's default 10,000-unit daily quota may be enough for only about six video inserts at 1,600 units each, so some attempts may fail from quota exhaustion. Each failed YouTube upload is saved to Google Drive when the video, thumbnail, and metadata exist; failures before those files exist are marked `skipped`. The planner does not reserve Drive-only slots in advance.

When `FACEBOOK_PAGE_ID` and `FACEBOOK_PAGE_ACCESS_TOKEN` are configured, batch videos are also scheduled to the Facebook Page, including videos whose YouTube upload fails and is saved to Drive. Facebook publishing uses its own credentials and does not consume YouTube API quota. If one platform succeeds and another fails, the calendar result records each platform's ID/link and the failed platform detail; the video is also retained in Drive for recovery.

### Daily-batch troubleshooting

- Gemini HTTP 429: the runner already backs off and rotates `GEMINI_API_KEY` / `GEMINI_API_KEY1`. Confirm both keys have usable quota; two keys from one exhausted Cloud project may share the same limit.
- YouTube `quotaExceeded` or `uploadLimitExceeded`: generated video files are saved to Drive. The Apps Script checks every two hours and retries only slots without a YouTube video ID while their publish time remains safely in the future. The manual `python recap\retry_failed_uploads.py --calendar calendar\content_calendar.json` command remains available to recover videos saved to Drive.
- Google Drive HTTP 403: the existing refresh token likely lacks `drive.file`. Regenerate the token with `python tools\get_refresh_token.py`, enable Drive API in the same project, and replace the Actions secret.

The existing YouTube refresh token does not gain Drive permission automatically. Enable Google Drive API in the same Google Cloud project, then run `python tools\get_refresh_token.py` locally with `YT_CLIENT_ID` and `YT_CLIENT_SECRET` set. Copy its output into the `YT_REFRESH_TOKEN` Actions secret. The OAuth consent screen should be **In production**: tokens from an app left in **Testing** may expire after seven days (otherwise regenerate weekly). The refreshed grant includes `youtube.upload`, `youtube.readonly`, and `drive.file`. To retry saved videos after quota resets, run `python recap\retry_failed_uploads.py --calendar calendar\content_calendar.json`.

For Facebook cross-posting from the batch workflow, set `FACEBOOK_PAGE_ACCESS_TOKEN` as an Actions secret and `FACEBOOK_PAGE_ID` as a secret or repository variable. The Page token needs permission to publish Page videos (`pages_manage_posts`).

The Apps Script is the daily orchestrator: it dispatches the legacy single-video workflow and the 10-slot batch workflow, and the batch excludes the legacy-managed 09:00 slot. GitHub cron remains disabled.

## Legacy single-video calendar publishing

The researched calendar at `data/india-festival-video-calendar-2026.json` contains one sourced video brief for every date from November 11 through December 31, 2026, including evergreen culture topics. The daily Google Apps Script runs near 02:05 IST. It dispatches the batch for two days ahead and the legacy video for the next day's 09:00 IST release; both workflows share a concurrency group. The legacy workflow uses its existing source-validation logic and schedules publication two days before its calendar target date. Apps Script triggers run near the selected minute, not at an exact second; the script rejects a legacy release time that is less than 15 minutes away.

To enable the daily trigger:

1. Copy `scheduler/google_apps_script.gs` into a new project at [script.google.com](https://script.google.com).
2. In **Project Settings → Script properties**, add `GITHUB_PAT` with a token that can read workflow runs and dispatch/rerun Actions in this repository (`Actions: read and write` for a fine-grained token; a classic token needs `repo` and `workflow`).
3. Run `setupDailyTrigger()` once and authorize the requested permissions. It installs the 02:05 daily dispatcher and a separate every-two-hours verification/retry trigger. Check Apps Script **Executions** and GitHub Actions job summaries for per-video results and retry errors.
4. Ensure the repository has `GEMINI_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN` Actions secrets. The YouTube refresh token needs `youtube.upload` and `youtube.readonly` scopes. To schedule the same video on Facebook, add `FACEBOOK_PAGE_ACCESS_TOKEN` as an Actions secret and `FACEBOOK_PAGE_ID` as an Actions variable (the page ID can also be a secret). The Page token must have Page publishing access and the app must have the required Page publishing permission (`pages_manage_posts`). Facebook uses the Page-token resumable video-upload flow and does not require `META_APP_ID` or `META_USER_ACCESS_TOKEN`.

To manually rerun today's dispatch, replace the project code with the current `scheduler/google_apps_script.gs`, then select and run `dispatchTodaysFestivalVideo()` from the Apps Script editor. Legacy and batch dispatches are tracked separately in Script Properties, so a failed batch dispatch can be retried without dispatching the legacy video twice.

The workflow receives the calendar target date, topic, and researched source notes, writes the script, renders a video and thumbnail, uploads the custom thumbnail to YouTube, and can schedule YouTube and Facebook Page publication at 09:00 IST two days before the target date. If the generated narration is under 800 words, it requests up to two longer drafts using the same research context; synthesized audio must still pass the six-minute minimum. YouTube and Facebook uploads have separate controls so a failed platform can be retried without attempting a duplicate upload to the other. YouTube requires scheduled videos to be private until its publish time. Facebook uses Meta's resumable video-upload API and a scheduled Page video post. Configure channel defaults and audience/restrictions in YouTube Studio as needed.

The legacy workflow attempts the YouTube upload before using Drive. If an enabled platform upload fails after rendering, it saves the generated video, thumbnail, and metadata to Google Drive and reports the Drive link. If both uploads succeed, no Drive copy is made.

Video metadata includes the festival/topic and supported year in the title when they fit naturally, a Hindi description with the summary, chapters, regional caveats, search phrases, and cited source links, plus deduplicated Hindi and English tags and a small set of relevant hashtags.

## GitHub Actions

The manual workflow runs on a GitHub-hosted Ubuntu runner and installs Chromium for DeepAI image generation. It uses Gemini Google Search grounding when quota is available; on explicit grounding quota exhaustion it falls back to key-free DuckDuckGo/Bing search, opens source pages, and uses standard Gemini generation with those excerpts. The report records the source links and research method. No YouTube transcripts are collected.

Add `GEMINI_API_KEY` and `GEMINI_API_KEY1` (optional backup) plus the existing YouTube OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN`) as repository Actions secrets. To schedule a Facebook Page video, set `FACEBOOK_PAGE_ID` as a secret or variable and `FACEBOOK_PAGE_ACCESS_TOKEN` as a secret. The Page token must have Page publishing access and the app must have `pages_manage_posts`; this flow does not use a separate Meta App ID or user access token. You may set `META_GRAPH_API_VERSION` as a variable; it defaults to `v27.0`. Gemini research tries stable Flash models and Flash-Lite fallbacks, then the backup key; temporary rate limits and server errors are retried. Explicitly exhausted Google Search grounding quota switches to key-free web search rather than waiting through retries. GitHub Actions does not inject Cloudflare credentials, avoiding accidental use of its potentially metered image API; it tries the public DeepAI page, Hugging Face FLUX, and Pollinations, then uses designed title cards if image services are unavailable. These public services can still rate-limit or change availability, and Gemini standard generation still requires available Gemini API quota. For scheduled uploads, the YouTube refresh token needs both `youtube.upload` and `youtube.readonly` (read access is used to check for duplicate titles). Run **Festival explainer video** manually with a topic, festival date, **publish date (YYYY-MM-DD)**, and **publish time (24-hour HH:MM IST)**. YouTube and Facebook uploads are separate disabled-by-default controls; enable the platform(s) you want to schedule.

To apply the checked-in Chhath Puja thumbnail to an already-uploaded video, run **Update scheduled video thumbnail** and provide its YouTube video ID. New video uploads attach their generated thumbnail automatically.

To retry a failed Facebook upload without regenerating or re-uploading to YouTube, run **Retry Facebook Page video** with the source Actions run ID and YouTube video ID. It downloads the original video and metadata, preserves the original title, description, and scheduled time, and attaches `assets/facebook/akshaya-navami-jagaddhatri-2026.jpg`.

On HTTP 429 `RESOURCE_EXHAUSTED`, check the Gemini API quota and billing for the Google Cloud projects behind both configured keys; adding another key from the same project may not add quota. On HTTP 403 stating that the Gemini API free tier is unavailable for the project, enable billing for the Google Cloud project associated with that key or use a key from a project that has Gemini API access. A different Gmail address alone does not guarantee a separate eligible API project or free-tier quota.

## Tests

```powershell
python -m unittest discover -s tests -v
```
