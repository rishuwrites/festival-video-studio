# Festival Video Studio

Create original Hindi festival explainers with research notes, original illustrations, narration, captions, background music, and a thumbnail.

## What it does

- Searches YouTube for relevant videos and requires public Hindi/English captions from **five distinct channels**.
- Compares source-video themes with current Google Search-grounded research.
- Requires at least two grounded web citations and records all source links in a research report.
- Generates an original 9–12 chapter Hindi script. Source captions are research inputs only: they are never saved in the report or copied into the script.
- Verifies the synthesized narration lasts at least six minutes before rendering.
- Produces an MP4, thumbnail, metadata JSON, and a research JSON report.
- Never uploads or publishes automatically.

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

YouTube search can use your existing OAuth secrets (`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`) or an optional `YT_API_KEY`. OAuth must have YouTube read-only access (`youtube.readonly`) and YouTube Data API v3 must be enabled for the Google Cloud project. If your refresh token only has upload access, re-authorize it with the read-only scope. Use `--scope` to customize coverage, or the older `--location` option as an alias. For example, `--scope "India (nationwide, focus on UP and Bihar)"`. Image generation can use Cloudflare credentials; the configured image providers are tried as fallbacks. Output is written to `output\`.

## GitHub Actions

Add `GEMINI_API_KEY`, `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, and `YT_REFRESH_TOKEN` as repository Actions secrets. These are the existing serial-recap YouTube OAuth credentials; a separate `YT_API_KEY` is not required. The OAuth refresh token needs `youtube.readonly` access. Optionally add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Run **Festival explainer video** manually with a topic and date; its default scope covers India with a special focus on Uttar Pradesh and Bihar.

## Tests

```powershell
python -m unittest discover -s tests -v
```
