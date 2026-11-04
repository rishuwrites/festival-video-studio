import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import tempfile
from urllib.parse import urlparse

import config as S
import gemini
import images
import render
import voice
from festival_sources import find_transcribed_videos
from youtube_upload import scheduled_datetime, upload_scheduled


FESTIVAL_STYLE = (
    "original Indian festival editorial illustration, cinematic lighting, "
    "rich but natural colors, respectful culturally specific details, "
    "family friendly, no text, no letters, no logos, no watermark"
)
VALID_EMOTIONS = set(S.EMOTION_COLORS)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def validate_narration_duration(seconds):
    if seconds < 360:
        raise ValueError(
            f"Rendered narration is {seconds:.1f} seconds; at least 360 seconds (6 minutes) are required. "
            "Increase the script length before retrying."
        )


def validate_research(result):
    research = result.get("research")
    if not isinstance(research, dict):
        raise ValueError("Festival research did not return a JSON object")
    for field in ("headline", "thumbnail_text", "hook", "research_summary"):
        if not isinstance(research.get(field), str) or not research[field].strip():
            raise ValueError(f"Festival research is missing required field: {field}")
    if len(research["headline"]) > 100:
        raise ValueError("Festival video title must be 100 characters or fewer")
    if len(research["thumbnail_text"].split()) > 5:
        raise ValueError("Festival thumbnail text must be 5 words or fewer")
    if not isinstance(research.get("keywords"), list) or not research["keywords"]:
        raise ValueError("Festival research must return relevant keywords")
    if not isinstance(research.get("key_facts"), list) or not research["key_facts"]:
        raise ValueError("Festival research must return cited key facts for review")
    for fact in research["key_facts"]:
        if (not isinstance(fact, dict) or not isinstance(fact.get("claim"), str)
                or not fact["claim"].strip() or not isinstance(fact.get("source_titles"), list)
                or not fact["source_titles"]):
            raise ValueError("Festival key facts must include a claim and source titles")
    scenes = research.get("scenes")
    if not isinstance(scenes, list) or not 9 <= len(scenes) <= 12:
        raise ValueError("Festival research must return 9-12 scenes for a six-minute explainer")
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError(f"Festival scene {index} is not an object")
        for field in ("title", "narration", "visual_prompt", "emotion"):
            if not isinstance(scene.get(field), str) or not scene[field].strip():
                raise ValueError(f"Festival scene {index} is missing {field}")
        if scene["emotion"] not in VALID_EMOTIONS:
            raise ValueError(f"Festival scene {index} has unsupported emotion: {scene['emotion']}")
    sources = result.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Festival research sources are missing")
    video_sources = [source for source in sources if isinstance(source, dict) and source.get("kind") == "video_transcript"]
    web_sources = [
        source for source in sources
        if isinstance(source, dict) and source.get("kind") in ("grounded_web", "web_research")
    ]
    if video_sources and (
        len(video_sources) < 5 or len({source.get("channel_id") for source in video_sources}) < 5
    ):
        raise ValueError("If video captions are used, they must come from five distinct channels")
    if len(web_sources) < 2:
        raise ValueError("At least two web research source citations are required")
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not source["title"].strip():
            raise ValueError("Festival sources must include a title and an HTTPS URL")
        parsed_url = urlparse(str(source.get("url", "")))
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("Festival sources must include a title and an HTTPS URL")
    total_words = len(" ".join([research["hook"]] + [scene["narration"] for scene in scenes]).split())
    if total_words < 800:
        raise ValueError(f"Festival narration needs at least 800 words for a six-minute target; got {total_words}")
    available_titles = {source["title"] for source in sources}
    for fact in research["key_facts"]:
        if not set(fact["source_titles"]).intersection(available_titles):
            raise ValueError("Each researched key fact must cite a retrieved video or web source")
    return research


def _safe_slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        slug = "festival-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return slug[:60].strip("-")


def _make_description(topic, date, scope, research, sources):
    date_line = f"Requested date/year: {date}\n" if date else ""
    source_lines = "\n".join(f"- {source['title']}: {source['url']}" for source in sources[:8])
    return (
        f"{research['headline']}\n\n"
        f"{research['research_summary']}\n\n"
        f"Topic: {topic}\n{date_line}Coverage: {scope}\n\n"
        "Dates and customs can vary by panchang and regional tradition. "
        "Exact muhurta timings are city-specific; check a local panchang before relying on them.\n\n"
        f"Research sources:\n{source_lines}\n\n"
        "#Festival #Hindi #IndianCulture"
    )


def _research_mode(grounded, video_sources):
    if grounded.get("research_method") == "provided_web_research":
        return "video_transcripts_and_web_research" if video_sources else "web_research_only"
    return "video_transcripts_and_grounded_web" if video_sources else "grounded_web_only"


def _scene_image_count(duration):
    return max(1, math.ceil(duration / render.S.CUT_SECONDS))


def _shot_prompt(scene, shot_index, shot_count):
    angles = (
        "wide establishing composition showing the full setting and surrounding decorations",
        "medium composition focused on the main action and subject placement",
        "close detail composition of a relevant cultural object, hands, or decoration",
        "over-the-shoulder composition revealing the setting and point of attention",
        "slightly elevated composition emphasizing the layout, lights, and environment",
        "side-angle composition with clear foreground and background depth",
    )
    angle = angles[shot_index % len(angles)]
    return (
        f"{scene['visual_prompt']}. Create an original educational illustration for shot "
        f"{shot_index + 1} of {shot_count}. Camera composition: {angle}. "
        "Keep the same scene, character appearance, clothing, and art style across shots. "
        "No text, letters, logos, watermark, or depiction of a real person."
    )


def _collect_video_research_sources(topic, date, scope):
    transcript_research = os.getenv("FESTIVAL_TRANSCRIPT_RESEARCH", "true").strip().lower()
    if transcript_research in ("0", "false", "no", "off"):
        if os.getenv("FESTIVAL_RESEARCH_CONTEXT", "").strip():
            print("Video transcript research disabled; using supplied web research and plain Gemini generation")
        else:
            print("Video transcript research disabled; using Google Search-grounded research")
        return []
    print("Finding five distinct channels with accessible public captions")
    return find_transcribed_videos(topic, date, scope)


def generate_video(
    topic, date="", scope=S.DEFAULT_SCOPE, output_dir=None,
    publish_date="", publish_time="", upload=False,
):
    if not topic.strip():
        raise ValueError("A festival topic is required")
    if upload:
        scheduled_datetime(publish_date, publish_time)
    scope = scope.strip() or S.DEFAULT_SCOPE
    video_sources = _collect_video_research_sources(topic.strip(), date.strip(), scope)
    grounded = gemini.research_festival(
        topic.strip(),
        date.strip(),
        scope,
        video_sources=video_sources,
        web_research=os.getenv("FESTIVAL_RESEARCH_CONTEXT", "").strip() or None,
    )
    research = validate_research(grounded)

    output_dir = output_dir or os.path.join(S.BASE, "output")
    os.makedirs(output_dir, exist_ok=True)
    slug = _safe_slug(topic)
    day_slug = _safe_slug(date) if date else dt.datetime.now(IST).strftime("%Y%m%d")
    scope_slug = _safe_slug(scope)[:24]
    basename = f"festival_{slug}_{day_slug}_{scope_slug}"
    video_path = os.path.join(output_dir, basename + ".mp4")
    thumb_path = os.path.join(output_dir, basename + ".jpg")
    metadata_path = os.path.join(output_dir, basename + ".json")
    research_path = os.path.join(output_dir, basename + "_research.json")
    report = {
        "generated_at_ist": dt.datetime.now(IST).isoformat(),
        "topic": topic,
        "date": date,
        "coverage_scope": scope,
        "research_mode": _research_mode(grounded, video_sources),
        "research_summary": research["research_summary"],
        "key_facts": research["key_facts"],
        "search_queries": grounded.get("search_queries", []),
        "sources": grounded["sources"],
        "video_sources_analyzed": len([
            source for source in grounded["sources"] if source.get("kind") == "video_transcript"
        ]),
        "research_mode": _research_mode(grounded, video_sources),
        "script": {
            "hook": research["hook"],
            "scenes": research["scenes"],
        },
        "review_required_before_publication": True,
    }
    with open(research_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    with tempfile.TemporaryDirectory(prefix=f"festival_{slug}_") as tmp:
        scenes = research["scenes"]
        segments = [{
            "tag": "hook",
            "lines": [research["hook"]],
            "img": 0,
            "chip": "आज का पर्व",
            "name": "मुख्य सवाल",
            "emo": scenes[0]["emotion"],
        }]
        for index, scene in enumerate(scenes):
            segments.append({
                "tag": f"scene{index}",
                "lines": [scene["narration"]],
                "img": index,
                "chip": f"जानकारी {index + 1}/{len(scenes)}",
                "name": scene["title"],
                "emo": scene["emotion"],
            })
        segments.append({
            "tag": "outro",
            "lines": [
                "तिथि और मुहूर्त के लिए अपने शहर के विश्वसनीय पंचांग और नीचे दिए स्रोत ज़रूर देखें।",
                "जानकारी उपयोगी लगी हो तो वीडियो साझा करें।",
            ],
            "img": len(scenes) - 1,
            "chip": "धन्यवाद",
            "name": "",
            "emo": "happy",
        })
        voice.synth_all(segments, tmp)
        total = sum(segment["times"][-1][1] for segment in segments)
        validate_narration_duration(total)

        seed = int(hashlib.sha256(f"{topic}|{date}|{scope}".encode("utf-8")).hexdigest()[:8], 16)
        compositions = {index: [] for index in range(len(scenes))}
        generated = set()
        for index, scene in enumerate(scenes):
            shot_count = _scene_image_count(segments[index + 1]["times"][-1][1])
            for shot_index in range(shot_count):
                raw_path = os.path.join(tmp, f"scene_{index}_shot_{shot_index}.jpg")
                comp_path = os.path.join(tmp, f"comp_{index}_shot_{shot_index}.jpg")
                prompt = _shot_prompt(scene, shot_index, shot_count)
                shot_seed = seed + index * 100 + shot_index
                if images.generate(prompt, shot_seed, raw_path, style=FESTIVAL_STYLE):
                    render.cover(raw_path, comp_path)
                    compositions[index].append(comp_path)
            if compositions[index]:
                generated.add(index)
        for missing, source in images.reuse_nearest_generated_images(compositions, generated):
            print(f"  scene {missing + 1}: reusing original artwork from scene {source + 1}")
        if not generated:
            print("  no generated illustrations available; using designed Hindi title cards")
            for index, scene in enumerate(scenes):
                card_path = os.path.join(tmp, f"card_{index}.jpg")
                render.card(scene["title"], scene["emotion"], card_path)
                compositions[index].append(card_path)
        for index, scene in enumerate(scenes):
            shot_count = _scene_image_count(segments[index + 1]["times"][-1][1])
            while len(compositions[index]) < shot_count:
                shot_index = len(compositions[index])
                comp_path = os.path.join(tmp, f"comp_{index}_fallback_{shot_index}.jpg")
                render.reframe(compositions[index][shot_index % len(compositions[index])], comp_path, shot_index)
                compositions[index].append(comp_path)

        files = []
        starts = []
        offset = 0.0
        for index, segment in enumerate(segments):
            segment_path = os.path.join(tmp, f"segment_{segment['tag']}.mp4")
            duration = render.segment(
                segment["tag"],
                "पर्व और परंपरा",
                segment["chip"],
                segment["emo"],
                segment["lines"],
                segment["times"],
                segment["audio"],
                compositions[segment["img"]],
                tmp,
                segment_path,
                offset,
                total,
                v0=index,
                word_times=segment.get("word_times"),
            )
            files.append(segment_path)
            if segment["name"]:
                starts.append({"seconds": round(offset), "chapter": segment["name"]})
            offset += duration

        primary_emotion = scenes[0]["emotion"]
        music = render.auto_music(tmp, offset, emotion=primary_emotion)
        render.concat(files, tmp, video_path, music, offset, emotion=primary_emotion)

        thumbnail_prompt = (
            f"Create an original 16:9 YouTube explainer thumbnail illustration about {topic}. "
            f"Scene inspiration: {scenes[0]['visual_prompt']}. "
            "Culturally respectful Indian festival imagery, strong clear composition, "
            "bright cinematic lighting, open lower third for Hindi overlay text. "
            "Do not draw text, letters, logos, or a watermark."
        )
        thumbnail_art = os.path.join(tmp, "thumbnail_art.jpg")
        if not images.generate_thumbnail(thumbnail_prompt, seed + 1001, thumbnail_art, style=FESTIVAL_STYLE):
            thumbnail_art = compositions[0][0]
        render.thumbnail(
            thumbnail_art,
            research["thumbnail_text"],
            "पर्व विशेष",
            f"भारत | {date or 'जानकारी'}",
            thumb_path,
        )

    description = _make_description(topic, date, scope, research, grounded["sources"])
    keywords = [str(keyword) for keyword in research.get("keywords", []) if str(keyword).strip()]
    metadata = {
        "title": research["headline"],
        "description": description,
        "tags": keywords[:20],
        "topic": topic,
        "date": date,
        "coverage_scope": scope,
        "duration_seconds": round(offset),
        "chapters": starts,
        "sources": grounded["sources"],
        "search_queries": grounded.get("search_queries", []),
        "video_sources_analyzed": len([
            source for source in grounded["sources"] if source.get("kind") == "video_transcript"
        ]),
        "research_mode": _research_mode(grounded, video_sources),
        "narration_seconds": round(total),
        "video": os.path.basename(video_path),
        "thumbnail": os.path.basename(thumb_path),
        "upload_status": "not_uploaded_review_required",
    }
    with open(metadata_path, "w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    if upload:
        if not publish_date or not publish_time:
            raise ValueError("Scheduled upload requires a publish date and time in IST")
        print(f"  scheduling YouTube upload for {publish_date} {publish_time} IST")
        youtube_result = upload_scheduled(video_path, metadata_path, publish_date, publish_time)
        metadata.update({
            "upload_status": youtube_result["status"],
            "youtube_video_id": youtube_result["video_id"],
            "youtube_url": youtube_result["url"],
            "publish_at_ist": youtube_result["publish_at_ist"],
        })
        with open(metadata_path, "w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
        print(f"  YouTube scheduled: {youtube_result['url']} at {youtube_result['publish_at_ist']}")

    print(f"  rendered preview: {video_path}")
    print(f"  research report: {research_path}")
    if not upload:
        print("  YouTube upload is disabled; review the claims, dates, source links, and local timings")
    return {
        "video": video_path,
        "thumbnail": thumb_path,
        "metadata": metadata_path,
        "research": research_path,
        "youtube": metadata.get("youtube_url", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Create a source-grounded Hindi festival explainer video")
    parser.add_argument("--topic", default=os.getenv("FESTIVAL_TOPIC", ""), help="Festival or observance to explain")
    parser.add_argument("--date", default=os.getenv("FESTIVAL_DATE", ""), help="Optional date/year, for example 2026")
    parser.add_argument(
        "--scope",
        "--location",
        dest="scope",
        default=os.getenv("FESTIVAL_SCOPE") or S.DEFAULT_SCOPE,
        help="Coverage scope; defaults to India-wide with focus on Uttar Pradesh and Bihar",
    )
    parser.add_argument("--output-dir", default=os.getenv("FESTIVAL_OUTPUT_DIR", ""))
    parser.add_argument("--publish-date", default=os.getenv("FESTIVAL_PUBLISH_DATE", ""), help="Scheduled publish date (YYYY-MM-DD, IST)")
    parser.add_argument("--publish-time", default=os.getenv("FESTIVAL_PUBLISH_TIME", ""), help="Scheduled publish time (HH:MM, 24-hour IST)")
    parser.add_argument(
        "--upload",
        action="store_true",
        default=os.getenv("YOUTUBE_UPLOAD", "").strip().lower() in ("1", "true", "yes", "on"),
        help="Upload as a private video scheduled for the selected date and time",
    )
    args = parser.parse_args()
    if not args.topic.strip():
        parser.error("--topic or FESTIVAL_TOPIC is required")
    try:
        generate_video(
            args.topic, args.date, args.scope, args.output_dir or None,
            args.publish_date, args.publish_time, args.upload,
        )
    except Exception as exc:
        raise SystemExit(f"Festival video generation failed: {type(exc).__name__}: {exc}") from exc


if __name__ == "__main__":
    main()
