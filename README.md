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

For Panchang dates and muhurta, provide a city. Calendar details can vary by location and tradition; verify the cited sources before publishing.

## Run locally

Install Python dependencies and FFmpeg. On Windows, install a Devanagari font such as Nirmala UI. Set API keys in the shell; do not commit them:

```powershell
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "..."
$env:YT_API_KEY = "..."
python recap\festival_main.py --topic "Dhanteras" --date "2026" --location "Jaipur, Rajasthan"
```

Video search uses a YouTube Data API key. Image generation can use Cloudflare credentials; the configured image providers are tried as fallbacks. Output is written to `output\`.

## GitHub Actions

Add `GEMINI_API_KEY` and `YT_API_KEY` as repository Actions secrets. Optionally add `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`. Run **Festival explainer video** manually with a topic, date, and location, then download the artifact.

## Tests

```powershell
python -m unittest discover -s tests -v
```
