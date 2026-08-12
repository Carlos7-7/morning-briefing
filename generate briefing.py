"""
Morning Briefing generator.

Run daily by GitHub Actions. Pulls headlines from RSS feeds, has Claude
write a spoken-word script personalized to the configured topics, converts
it to audio with OpenAI TTS, and rebuilds the podcast RSS feed that
Pocket Casts (or any podcast app) subscribes to.
"""

import os
import re
import json
import glob
import datetime
import subprocess

import feedparser
import requests
from anthropic import Anthropic
from openai import OpenAI
from feedgen.feed import FeedGenerator

CONFIG_FILE = "topics.json"
EPISODES_DIR = "episodes"
FEED_FILE = "podcast.xml"
RETENTION_DAYS = 14

SCRIPT_MODEL = "claude-haiku-4-5-20251001"
TTS_MODEL = "gpt-4o-mini-tts"
VOICE = "cedar"

# The delivery style. Tweak this line to change how it sounds.
VOICE_INSTRUCTIONS = (
    "Brisk, clear newsreader - efficient radio pace, neutral authority. "
    "Minimal pauses between sentences, tight transitions, no dead air. "
    "Reads through commas smoothly without breaking, only pausing at periods."
)

# The TTS model caps input at 2000 tokens, so long scripts get split.
# Chunks break on sentence boundaries so the seams aren't audible.
MAX_CHUNK_CHARS = 3000


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def strip_html(text):
    return re.sub("<[^<]+?>", "", text or "").strip()


def fetch_topic_content(feed_urls, max_items_per_feed=4):
    items = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
            source_name = parsed.feed.get("title", url)
            for entry in parsed.entries[:max_items_per_feed]:
                items.append({
                    "title": strip_html(entry.get("title", "")),
                    "summary": strip_html(entry.get("summary", entry.get("description", "")))[:600],
                    "author": entry.get("author", ""),
                    "link": entry.get("link", ""),
                    "source": source_name,
                })
        except Exception as e:
            print(f"WARNING: failed to fetch {url}: {e}")
    return items


def fetch_weather(lat, lon):
    headers = {"User-Agent": "carlos-morning-briefing (personal project)"}
    try:
        points = requests.get(
            f"https://api.weather.gov/points/{lat},{lon}", headers=headers, timeout=10
        ).json()
        forecast_url = points["properties"]["forecast"]
        forecast = requests.get(forecast_url, headers=headers, timeout=10).json()
        today = forecast["properties"]["periods"][0]
        return f"{today['name']}: {today['detailedForecast']}"
    except Exception as e:
        print(f"WARNING: weather fetch failed: {e}")
        return "Weather data wasn't available this morning."


def build_prompt(all_content, weather_text, date_str):
    sections = []
    for topic, items in all_content.items():
        if not items:
            continue
        block = f"## {topic}\n"
        for it in items:
            block += f"- \"{it['title']}\" ({it['source']}, by {it['author'] or 'staff'}): {it['summary']}\n"
        sections.append(block)
    content_blob = "\n\n".join(sections)

    return f"""You are writing today's ({date_str}) spoken-word script for a private, \
single-listener morning news podcast. The listener is named Carlos. This is for his \
ears only, not a public broadcast.

Write natural, flowing spoken prose meant to be read aloud by text-to-speech - NOT \
bullet points, NOT markdown, NOT headers. Cover the following in order:

1. A brief good-morning open mentioning today's date.
2. Today's weather: {weather_text}
3. Then work through, in order: Politics and Elections, Geopolitics and Global News, \
Local and Regional Tri-State News, Space, Science, Technology and AI, Economy and \
Markets, Sports, and Automotive. Use natural verbal transitions between each \
("Turning to...", "In sports...", "On the economic front...").
4. Close with a "worth reading yourself" segment: pick the ONE most newsworthy or \
zeitgeist-y article from everything below. Do NOT summarize it - just flag it by \
title, author, and outlet, and tell Carlos it's worth pulling up himself.
5. A short, warm sign-off.

PUNCTUATION RULES (important - this text is read by a speech model, and heavy \
punctuation creates unnatural mid-sentence pauses):
- Use short, direct sentences. Prefer two short sentences over one long one.
- Avoid em dashes, semicolons, colons, and parentheses entirely.
- Keep commas to a minimum - only where genuinely needed for clarity.
- Spell out numbers, symbols, and abbreviations the way they should be spoken \
(say "twenty twenty six" not "2026", "percent" not "%", "Doctor" not "Dr.").

Target length: 4000-4500 words (about 20-30 minutes read aloud). Skip any topic \
entirely if there's genuinely no source material for it below rather than padding.

Source material for today, organized by topic:

{content_blob}

Write the complete script now, with no preamble or notes - just the script itself."""


def generate_script(prompt):
    client = Anthropic()  # reads ANTHROPIC_API_KEY from environment
    message = client.messages.create(
        model=SCRIPT_MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def split_into_chunks(text, max_chars=MAX_CHUNK_CHARS):
    """Split on sentence boundaries so audio seams land between sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return chunks


def text_to_speech(script_text, mp3_path):
    client = OpenAI()  # reads OPENAI_API_KEY from environment
    chunks = split_into_chunks(script_text)
    print(f"Generating audio in {len(chunks)} chunks...")

    part_paths = []
    for i, chunk in enumerate(chunks):
        part_path = f"{EPISODES_DIR}/_part_{i:03d}.mp3"
        with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=VOICE,
            input=chunk,
            instructions=VOICE_INSTRUCTIONS,
        ) as response:
            response.stream_to_file(part_path)
        part_paths.append(part_path)
        print(f"  chunk {i + 1}/{len(chunks)} done")

    # Stitch the parts into one file, then clean up the pieces.
    list_path = f"{EPISODES_DIR}/_concat.txt"
    with open(list_path, "w") as f:
        for p in part_paths:
            f.write(f"file '{os.path.basename(p)}'\n")

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
         "-c", "copy", mp3_path],
        check=True,
    )

    for p in part_paths + [list_path]:
        os.remove(p)


def cleanup_old_episodes():
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=RETENTION_DAYS)
    for meta_path in glob.glob(f"{EPISODES_DIR}/*.json"):
        with open(meta_path) as f:
            meta = json.load(f)
        pub_date = datetime.datetime.fromisoformat(meta["pub_date"])
        if pub_date < cutoff:
            mp3_path = meta_path.replace(".json", ".mp3")
            for p in (meta_path, mp3_path):
                if os.path.exists(p):
                    os.remove(p)
            print(f"Removed expired episode: {meta_path}")


def build_feed(base_url):
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.title("Carlos's Morning Briefing")
    fg.link(href=base_url, rel="alternate")
    fg.description("A personalized daily morning news briefing. Narrated by an AI-generated voice.")
    fg.language("en-us")
    fg.podcast.itunes_category("News")
    fg.podcast.itunes_explicit("no")

    meta_files = sorted(glob.glob(f"{EPISODES_DIR}/*.json"), reverse=True)
    for meta_path in meta_files:
        with open(meta_path) as f:
            meta = json.load(f)
        fe = fg.add_entry()
        fe.id(f"{base_url}/{EPISODES_DIR}/{meta['filename']}")
        fe.title(meta["title"])
        fe.description(meta["description"])
        fe.enclosure(f"{base_url}/{EPISODES_DIR}/{meta['filename']}", 0, "audio/mpeg")
        fe.pubDate(meta["pub_date"])

    fg.rss_file(FEED_FILE)


def main():
    os.makedirs(EPISODES_DIR, exist_ok=True)
    config = load_config()

    repo = os.environ.get("GITHUB_REPOSITORY", "your-username/morning-briefing")
    owner, repo_name = repo.split("/")
    base_url = f"https://{owner}.github.io/{repo_name}"

    all_content = {topic: fetch_topic_content(feeds) for topic, feeds in config["topics"].items()}
    weather_text = fetch_weather(config["weather"]["latitude"], config["weather"]["longitude"])

    now = datetime.datetime.now(datetime.timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    prompt = build_prompt(all_content, weather_text, now.strftime("%B %d, %Y"))
    script_text = generate_script(prompt)

    mp3_filename = f"{date_str}.mp3"
    mp3_path = f"{EPISODES_DIR}/{mp3_filename}"

    text_to_speech(script_text, mp3_path)

    meta = {
        "filename": mp3_filename,
        "title": f"Morning Briefing - {now.strftime('%B %d, %Y')}",
        "description": "Your personalized morning news briefing. Narrated by an AI-generated voice.",
        "pub_date": now.isoformat(),
    }
    with open(f"{EPISODES_DIR}/{date_str}.json", "w") as f:
        json.dump(meta, f)

    cleanup_old_episodes()
    build_feed(base_url)

    print(f"Done. Episode saved as {mp3_path}")


if __name__ == "__main__":
    main()
