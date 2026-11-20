import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import tempfile
import unicodedata
from urllib.parse import urlparse

import config as S
import facebook_upload
import gemini
import images
import render
import voice
import web_search
from drive_fallback import save_to_drive
from youtube_upload import normalize_youtube_tags, scheduled_datetime, upload_scheduled


FESTIVAL_STYLE = (
    "original Indian festival editorial illustration, cinematic lighting, "
    "rich but natural colors, respectful culturally specific details, "
    "family friendly, no text, no letters, no logos, no watermark"
)
VALID_EMOTIONS = set(S.EMOTION_COLORS)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MIN_NARRATION_WORDS = 800
NARRATION_LENGTH_RETRIES = 2


class NarrationLengthError(ValueError):
    pass


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
        scene["overlay"] = _clean_overlay(scene.get("overlay"))
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
    if total_words < MIN_NARRATION_WORDS:
        raise NarrationLengthError(
            f"Festival narration needs at least {MIN_NARRATION_WORDS} words for a six-minute target; got {total_words}"
        )
    available_titles = {source["title"] for source in sources}
    for fact in research["key_facts"]:
        if not set(fact["source_titles"]).intersection(available_titles):
            raise ValueError("Each researched key fact must cite a retrieved video or web source")
    return research


def _clean_overlay(raw):
    """Overlay cards are optional decoration: sanitise them and drop anything unusable."""
    if not isinstance(raw, dict):
        return None
    text = " ".join(str(raw.get("text") or "").split())
    if not text:
        return None
    return {
        "label": " ".join(str(raw.get("label") or "जानकारी").split()[:3]),
        "text": " ".join(text.split()[:16]),
        "source_title": str(raw.get("source_title") or "").strip(),
    }


def _overlay_for_scene(scene, sources):
    """Attach a short source domain to a scene overlay when its source_title matches a real source."""
    overlay = scene.get("overlay")
    if not overlay:
        return None
    domain = ""
    for source in sources:
        if source.get("title") == overlay.get("source_title"):
            domain = urlparse(source.get("url", "")).netloc.removeprefix("www.")
            break
    return {**overlay, "source": domain}


def _thumbnail_badge(research):
    words = " ".join(str(research.get("headline", "")).split()).split()
    return " ".join(words[:2]) or "पूरी जानकारी"


def _thumbnail_date_label(date):
    month_names = (
        "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
        "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर",
    )
    try:
        parsed = dt.date.fromisoformat(date)
    except (TypeError, ValueError):
        return f"भारत | {date or 'पर्व विशेष'}"
    return f"{parsed.day} {month_names[parsed.month - 1]} {parsed.year}"


def _safe_slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        slug = "festival-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return slug[:60].strip("-")


def _make_description(topic, date, scope, research, sources, disclaimer="",
                      title_max_length=100, title_suffix="", festival_tradition=""):
    date_line = f"तिथि/वर्ष: {date}\n" if date else ""
    chapters = [
        str(scene.get("title", "")).strip()
        for scene in research.get("scenes", [])
        if str(scene.get("title", "")).strip()
    ]
    source_lines = "\n".join(
        f"- {source['title']}: {source['url']}" for source in sources[:10]
    )
    keywords = _video_tags(topic, date, research)
    hashtag_candidates = [topic, *research.get("keywords", [])]
    hindi_phrase = next(
        (phrase for phrase in hashtag_candidates if re.search(r"[\u0900-\u097f]", phrase)),
        "भारतीय संस्कृति",
    )
    english_phrase = next(
        (phrase for phrase in hashtag_candidates
         if re.search(r"[A-Za-z]", phrase) and not re.search(r"[\u0900-\u097f]", phrase)),
        "IndianCulture",
    )
    hashtags = []
    for phrase in (hindi_phrase, english_phrase, topic, *keywords):
        hashtag = "".join(
            character for character in phrase
            if character.isalnum() or unicodedata.category(character).startswith("M")
        )
        if hashtag and hashtag.casefold() not in {tag.casefold() for tag in hashtags}:
            hashtags.append(hashtag)
        if len(hashtags) == 4:
            break
    title = _video_title(
        topic, date, research["headline"], max_length=title_max_length,
        unique_suffix=title_suffix,
    )
    description_parts = [
        title,
        research["research_summary"].strip(),
        f"इस हिंदी वीडियो में {topic} की तिथि, महत्व, प्रमुख परंपराओं और अलग-अलग क्षेत्रों में प्रचलित रीति-रिवाजों की स्रोत-आधारित जानकारी दी गई है।",
        "इस वीडियो में: " + " • ".join(chapters[:12]) if chapters else "",
        f"विषय: {topic}",
        date_line.rstrip(),
        f"परंपरा: {festival_tradition}" if festival_tradition.strip() else "",
        disclaimer,
        f"क्षेत्र: {scope}",
        "पंचांग की तिथियां और मुहूर्त स्थान तथा परंपरा के अनुसार बदल सकते हैं। अपने शहर के विश्वसनीय पंचांग से पुष्टि करें।",
        "वीडियो उपयोगी लगे तो इसे साझा करें और ऐसे ही स्रोत-आधारित हिंदी सांस्कृतिक वीडियो के लिए चैनल को सब्सक्राइब करें।",
        f"मुख्य खोजशब्द: {', '.join(keywords[:12])}",
        f"स्रोत और आगे पढ़ें:\n{source_lines}" if source_lines else "",
        " ".join(f"#{tag}" for tag in hashtags),
    ]
    return "\n\n".join(part for part in description_parts if part)[:5000]


def _video_title(topic, date, headline, max_length=100, unique_suffix=""):
    title = " ".join(str(headline).split())
    year_match = re.search(r"\b(?:19|20)\d{2}\b", date or "")
    year = year_match.group(0) if year_match else ""
    if max_length < 30 or max_length > 100:
        raise ValueError("Video title limit must be between 30 and 100 characters")
    if unique_suffix or max_length < 100:
        suffix_parts = [value for value in (topic, year, unique_suffix)
                        if value and value.casefold() not in title.casefold()]
        suffix = " | " + " ".join(suffix_parts) if suffix_parts else ""
        if len(suffix) >= max_length:
            suffix = " | " + suffix[-(max_length - 3):]
        return title[:max_length - len(suffix)].rstrip() + suffix
    suffix_parts = [value for value in (topic, year) if value and value.casefold() not in title.casefold()]
    suffix = " | " + " ".join(suffix_parts) if suffix_parts else ""
    if len(title) + len(suffix) > 100 and year and year not in title:
        suffix = f" | {year}"
    if len(title) + len(suffix) > 100:
        suffix = ""
    title += suffix
    return title[:100].rstrip()


def _video_tags(topic, date, research):
    year_match = re.search(r"\b(?:19|20)\d{2}\b", date or "")
    year = year_match.group(0) if year_match else ""
    candidates = [
        topic,
        f"{topic} {year}" if year else "",
        f"{topic} date {year}" if year else "",
        f"{topic} in Hindi",
        "festival in India",
        "Indian culture",
        "हिंदी में त्योहार",
        "भारतीय त्योहार",
        *research.get("keywords", []),
    ]
    return normalize_youtube_tags(candidates)


def _research_mode(grounded):
    return grounded.get("research_method") or "gemini_google_search_grounded"


def _research_with_gemini(topic, date, scope, script_length_feedback=""):
    research_context = os.getenv("FESTIVAL_RESEARCH_CONTEXT", "").strip()
    length_feedback = (
        {"script_length_feedback": script_length_feedback}
        if script_length_feedback else {}
    )
    if research_context:
        print("Researching the festival from the sourced calendar context")
        return gemini.research_festival(
            topic, date, scope, video_sources=[], web_research=research_context,
            **length_feedback,
        )

    print("Researching the festival and writing the script through Gemini API Google Search grounding")
    try:
        return gemini.research_festival(
            topic, date, scope, video_sources=[],
            **length_feedback,
        )
    except RuntimeError as exc:
        message = str(exc).lower()
        if "http 429" not in message and "free tier" not in message:
            raise

        print("  Gemini Search grounding is unavailable; trying key-free web search with standard Gemini generation")
        collected = web_search.collect_pages(topic, date, scope)
        pages = collected.get("pages") or []
        if len(pages) < 2:
            raise RuntimeError(
                "Gemini Search grounding is quota-limited and key-free web search found fewer than two usable sources"
            ) from exc
        context = {
            "notes": "\n\n".join(
                f"[{page['title']}]\n{page['text']}" for page in pages
            )[:12000],
            "sources": [{"title": page["title"], "url": page["url"]} for page in pages],
            "search_queries": collected.get("search_queries", []),
        }
        return gemini.research_festival(
            topic, date, scope, video_sources=[], web_research=context,
            **length_feedback,
        )


def _research_and_validate(topic, date, scope):
    grounded = _research_with_gemini(topic, date, scope)
    for attempt in range(NARRATION_LENGTH_RETRIES + 1):
        try:
            return grounded, validate_research(grounded)
        except NarrationLengthError:
            if attempt >= NARRATION_LENGTH_RETRIES:
                raise
            print(
                f"  narration is below {MIN_NARRATION_WORDS} words; "
                f"requesting a longer sourced draft ({attempt + 1}/{NARRATION_LENGTH_RETRIES})"
            )
            grounded = _research_with_gemini(
                topic,
                date,
                scope,
                script_length_feedback=(
                    "The previous draft was below the required 800 spoken-word minimum. "
                    "Write at least 1,100 spoken Hindi words across the hook and scene narration "
                    "(aim for 1,100-1,200 words), then verify the count before returning the JSON. "
                    "Expand factual explanations, customs, regional distinctions, and source-supported "
                    "caveats rather than repeating points."
                ),
            )


def _validate_prepared_bundle(bundle):
    research = bundle.get("research")
    if not isinstance(research, dict):
        raise ValueError("Prepared video content must include a research object")
    for field in ("headline", "thumbnail_text", "hook", "research_summary"):
        if not isinstance(research.get(field), str) or not research[field].strip():
            raise ValueError(f"Prepared video content is missing required field: {field}")
    scenes = research.get("scenes")
    if not isinstance(scenes, list) or not 9 <= len(scenes) <= 12:
        raise ValueError("Prepared video content must contain 9-12 scenes")
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise ValueError(f"Prepared scene {index} must be an object")
        for field in ("title", "narration", "visual_prompt", "emotion"):
            if not isinstance(scene.get(field), str) or not scene[field].strip():
                raise ValueError(f"Prepared scene {index} is missing {field}")
        if scene["emotion"] not in VALID_EMOTIONS:
            raise ValueError(f"Prepared scene {index} has unsupported emotion")
    word_count = len(" ".join([research["hook"]] + [
        scene["narration"] for scene in scenes
    ]).split())
    if word_count < MIN_NARRATION_WORDS:
        raise NarrationLengthError(
            f"Prepared narration needs at least {MIN_NARRATION_WORDS} words; got {word_count}"
        )
    sources = bundle.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("Prepared video sources must be a list")
    for source in sources:
        parsed = urlparse(str(source.get("url", ""))) if isinstance(source, dict) else None
        if not isinstance(source, dict) or not source.get("title") or parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Prepared source citations must have a title and HTTPS URL")
    return research


def _scene_image_count(duration, interval_seconds=render.S.CUT_SECONDS):
    return max(1, math.ceil(duration / interval_seconds))


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


def _build_scene_compositions(scenes, scene_durations, seed, tmp, fixed_template, thumbnail_color=None):
    compositions = {index: [] for index in range(len(scenes))}
    generated = set()
    shot_counts = {}
    for index, scene in enumerate(scenes):
        shot_count = _scene_image_count(
            scene_durations[index],
            interval_seconds=60 if fixed_template else render.S.CUT_SECONDS,
        )
        shot_counts[index] = shot_count
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

    if generated:
        for missing, source in images.reuse_nearest_generated_images(compositions, generated):
            print(f"  scene {missing + 1}: reusing original artwork from scene {source + 1}")
    elif fixed_template:
        raise RuntimeError("No generated illustrations are available for the daily Panchang video")
    else:
        print("  no generated illustrations available; using designed Hindi title cards")
        for index, scene in enumerate(scenes):
            card_path = os.path.join(tmp, f"card_{index}.jpg")
            render.card(scene["title"], scene["emotion"], card_path, color=thumbnail_color)
            compositions[index].append(card_path)

    for index, composition in compositions.items():
        while len(composition) < shot_counts[index]:
            shot_index = len(composition)
            comp_path = os.path.join(tmp, f"comp_{index}_fallback_{shot_index}.jpg")
            render.reframe(composition[shot_index % len(composition)], comp_path, shot_index)
            composition.append(comp_path)
    return compositions


def generate_video(
    topic, date="", scope=S.DEFAULT_SCOPE, output_dir=None,
    publish_date="", publish_time="", upload=False, facebook_upload_enabled=False,
    prepared_bundle=None, title_max_length=100, title_suffix="", festival_tradition="",
    continue_on_upload_errors=False, allow_existing_upload=False,
):
    if not topic.strip():
        raise ValueError("A festival topic is required")
    if upload or facebook_upload_enabled:
        scheduled_datetime(publish_date, publish_time)
    scope = scope.strip() or S.DEFAULT_SCOPE
    if prepared_bundle is None:
        grounded, research = _research_and_validate(topic.strip(), date.strip(), scope)
        fixed_template = False
    else:
        grounded = prepared_bundle
        research = _validate_prepared_bundle(grounded)
        fixed_template = bool(grounded.get("fixed_template"))

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
        "research_mode": _research_mode(grounded),
        "research_summary": research["research_summary"],
        "key_facts": research["key_facts"],
        "search_queries": grounded.get("search_queries", []),
        "sources": grounded["sources"],
        "video_sources_analyzed": len([
            source for source in grounded["sources"] if source.get("kind") == "video_transcript"
        ]),
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
                "overlay": _overlay_for_scene(scene, grounded["sources"]),
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

        seed = int(hashlib.sha256(f"{topic}|{date}|{scope}".encode("utf-8")).hexdigest()[:8], 16) % 2_000_000_000
        compositions = _build_scene_compositions(
            scenes,
            [segments[index + 1]["times"][-1][1] for index in range(len(scenes))],
            seed,
            tmp,
            fixed_template,
            thumbnail_color=grounded.get("thumbnail_color"),
        )

        files = []
        starts = []
        offset = 0.0
        for index, segment in enumerate(segments):
            segment_path = os.path.join(tmp, f"segment_{segment['tag']}.mp4")
            overlays = render.make_overlays(
                segment["tag"], segment["name"], segment.get("overlay"),
                segment["emo"], segment["times"][-1][1], tmp,
            )
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
                overlays=overlays,
            )
            files.append(segment_path)
            if segment["name"]:
                starts.append({"seconds": round(offset), "chapter": segment["name"]})
            offset += duration

        primary_emotion = scenes[0]["emotion"]
        music = render.auto_music(tmp, offset, emotion=primary_emotion)
        render.concat(files, tmp, video_path, music, offset, emotion=primary_emotion)

        thumbnail_prompt = (
            f"Create an original 16:9 YouTube thumbnail illustration about {topic}. "
            f"Scene inspiration: {scenes[0]['visual_prompt']}. "
            "Show a vivid, culturally respectful Indian festival moment with expressive people and meaningful "
            "ritual objects on the right half, warm golden-hour light, rich colors, and realistic editorial detail. "
            "Keep the left half visually simple with darker open space for large overlay text. "
            "The image itself must contain absolutely no text, letters, writing, signs, logos, or watermark."
        )
        thumbnail_art = os.path.join(tmp, "thumbnail_art.jpg")
        if fixed_template:
            thumbnail_art = compositions[0][0]
        elif not images.generate_thumbnail(
            thumbnail_prompt, seed + 1001, thumbnail_art, style=FESTIVAL_STYLE,
        ):
            thumbnail_art = compositions[0][0]
        render.thumbnail(
            thumbnail_art,
            research["thumbnail_text"],
            f"{_thumbnail_badge(research)} {grounded.get('thumbnail_symbol', '')}".strip(),
            _thumbnail_date_label(date),
            thumb_path,
            accent_color=grounded.get("thumbnail_color"),
        )

    description = _make_description(
        topic, date, scope, research, grounded["sources"],
        disclaimer=grounded.get("description_disclaimer", ""),
        title_max_length=title_max_length,
        title_suffix=title_suffix,
        festival_tradition=festival_tradition,
    )
    keywords = _video_tags(topic, date, research)
    video_title = _video_title(
        topic, date, research["headline"], max_length=title_max_length,
        unique_suffix=title_suffix,
    )
    metadata = {
        "title": video_title,
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
        "research_mode": _research_mode(grounded),
        "narration_seconds": round(total),
        "video": os.path.basename(video_path),
        "thumbnail": os.path.basename(thumb_path),
        "upload_status": "not_uploaded_review_required",
        "facebook_status": "not_uploaded_review_required",
    }
    with open(metadata_path, "w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    upload_errors = {}
    if upload:
        if not publish_date or not publish_time:
            raise ValueError("Scheduled upload requires a publish date and time in IST")
        print(f"  scheduling YouTube upload for {publish_date} {publish_time} IST")
        try:
            youtube_result = upload_scheduled(
                video_path, metadata_path, publish_date, publish_time,
                thumbnail_path=thumb_path,
                allow_existing=allow_existing_upload,
            )
            metadata.update({
                "upload_status": youtube_result["status"],
                "youtube_video_id": youtube_result["video_id"],
                "youtube_url": youtube_result["url"],
                "publish_at_ist": youtube_result["publish_at_ist"],
            })
            if youtube_result.get("thumbnail_error"):
                upload_errors["youtube_thumbnail"] = youtube_result["thumbnail_error"]
                metadata["thumbnail_upload_status"] = "failed"
                metadata["thumbnail_upload_error"] = youtube_result["thumbnail_error"]
        except (RuntimeError, ValueError, OSError) as exc:
            if not continue_on_upload_errors:
                raise
            upload_errors["youtube"] = f"{type(exc).__name__}: {exc}"
            metadata["upload_status"] = "failed"
            metadata["youtube_error"] = upload_errors["youtube"]
        with open(metadata_path, "w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
        if metadata.get("youtube_url"):
            print(
                f"  YouTube scheduled: {metadata['youtube_url']} "
                f"at {metadata['publish_at_ist']}"
            )
    if facebook_upload_enabled:
        print(f"  scheduling Facebook Page video for {publish_date} {publish_time} IST")
        try:
            facebook_result = facebook_upload.upload_scheduled(
                video_path,
                video_title,
                description,
                publish_date,
                publish_time,
                thumbnail_path=thumb_path,
            )
            metadata.update({
                "facebook_status": facebook_result["status"],
                "facebook_video_id": facebook_result["video_id"],
                "facebook_url": facebook_result["url"],
                "facebook_publish_at_ist": facebook_result["publish_at_ist"],
            })
        except (RuntimeError, ValueError, OSError) as exc:
            if not continue_on_upload_errors:
                raise
            upload_errors["facebook"] = f"{type(exc).__name__}: {exc}"
            metadata["facebook_status"] = "failed"
            metadata["facebook_error"] = upload_errors["facebook"]
        with open(metadata_path, "w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2)
        if metadata.get("facebook_url"):
            print(
                f"  Facebook Page video scheduled: {metadata['facebook_url']} "
                f"at {metadata['facebook_publish_at_ist']}"
            )

    print(f"  rendered preview: {video_path}")
    print(f"  research report: {research_path}")
    if not upload:
        print("  YouTube upload is disabled; review the claims, dates, source links, and local timings")
    if not facebook_upload_enabled:
        print("  Facebook upload is disabled")
    return {
        "video": video_path,
        "thumbnail": thumb_path,
        "metadata": metadata_path,
        "research": research_path,
        "youtube": metadata.get("youtube_url", ""),
        "facebook": metadata.get("facebook_url", ""),
        "upload_errors": upload_errors,
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
    parser.add_argument(
        "--facebook-upload",
        action="store_true",
        default=os.getenv("FACEBOOK_UPLOAD", "").strip().lower() in ("1", "true", "yes", "on"),
        help="Upload to the configured Facebook Page for the selected publish date and time",
    )
    args = parser.parse_args()
    if not args.topic.strip():
        parser.error("--topic or FESTIVAL_TOPIC is required")
    try:
        generated = generate_video(
            args.topic, args.date, args.scope, args.output_dir or None,
            args.publish_date, args.publish_time, args.upload, args.facebook_upload,
            continue_on_upload_errors=args.upload or args.facebook_upload,
            allow_existing_upload=True,
        )
        youtube_succeeded = bool(generated.get("youtube"))
        drive_link = ""
        if args.upload and not youtube_succeeded:
            drive = save_to_drive(
                generated["video"],
                generated["thumbnail"],
                generated["metadata"],
                3,
                "partial_upload_failure",
                publish_date=args.publish_date,
                publish_time=args.publish_time,
                calendar_date=args.publish_date,
            )
            drive_link = drive["drive_link"]
            print(f"  YouTube failure saved to Google Drive: {drive_link}")
        if args.upload:
            youtube_status = "scheduled" if youtube_succeeded else "failed"
            print(
                f"YouTube upload status: {'SUCCESS' if youtube_succeeded else 'FAILED'}"
                + (f" — {generated['youtube']}" if youtube_succeeded else "")
            )
            result_path = os.path.join(
                os.path.dirname(generated["metadata"]),
                f"RESULT_{args.publish_date}_legacy.json",
            )
            with open(generated["metadata"], encoding="utf-8") as metadata_file:
                video_metadata = json.load(metadata_file)
            with open(result_path, "w", encoding="utf-8") as result_file:
                json.dump({
                    "date": args.publish_date,
                    "slot": 3,
                    "status": "scheduled" if youtube_succeeded else "failed_saved_to_drive",
                    "youtube_status": youtube_status,
                    "youtube_video_id": video_metadata.get("youtube_video_id", ""),
                    "drive_link": drive_link,
                    "notes": "; ".join(
                        f"{platform} upload failed: {detail}"
                        for platform, detail in generated.get("upload_errors", {}).items()
                    ),
                }, result_file, ensure_ascii=False, indent=2)
            if not youtube_succeeded:
                raise SystemExit("YouTube upload failed; retry this legacy video later.")
    except Exception as exc:
        raise SystemExit(f"Festival video generation failed: {type(exc).__name__}: {exc}") from exc


if __name__ == "__main__":
    main()
