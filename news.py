# news.py
# The error you are seeing is an ENVIRONMENT issue. The fix is to create a
# virtual environment and install the libraries from requirements.txt as described.

import os
import logging
import shutil
import tempfile
import re
import subprocess
import requests
import math
import random
import asyncio
import edge_tts
import configparser
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin
import html

# --- Required Libraries Check ---
try:
    import spacy
    from matplotlib import font_manager
except ImportError:
    print("FATAL ERROR: A required library is not installed.")
    print("Please follow the instructions to create a virtual environment and run 'pip3 install -r requirements.txt'")
    exit()

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Constants ---
VIDEO_WIDTH, VIDEO_HEIGHT = 1080, 1920
HEADLINES_LIMIT = 4
MIN_CLIP_DURATION = 5
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
FONT_PATH, NLP_MODEL, UNSPLASH_API_KEY = None, None, None
VOICE = "en-US-AriaNeural"
HISTORY_FILE, DESCRIPTION_FILE, LAST_SEGMENT_FILE, CONFIG_FILE = "processed_urls.txt", "video_description.txt", "last_segment.txt", "config.ini"
FPS = 24
OUTRO_GIF_NAME = "snap_feed.gif"

# --- Reliable RSS & Custom Feeds ---
SEGMENT_SOURCES = {
    "Top Stories": [
        {"name": "The Leading Report", "url": "https://theleadingreport.com/", "type": "custom"},
        {"name": "Associated Press", "url": "https://storage.googleapis.com/afs-prod/feeds/topnews.xml"},
        {"name": "Reuters Top News", "url": "http://feeds.reuters.com/reuters/topNews"},
        {"name": "NPR News", "url": "https://feeds.npr.org/1001/rss.xml"},
    ],
    "Political": [
        {"name": "The Leading Report", "url": "https://theleadingreport.com/", "type": "custom"},
        {"name": "Reuters Politics", "url": "http://feeds.reuters.com/reuters/politicsNews"},
        {"name": "Politico", "url": "https://rss.politico.com/politico.xml"},
        {"name": "The Hill", "url": "https://thehill.com/rss/syndicator/19109"},
    ],
    "US National": [
        {"name": "Reuters US News", "url": "http://feeds.reuters.com/reuters/domesticNews"},
        {"name": "NPR National News", "url": "https://feeds.npr.org/1003/rss.xml"},
        {"name": "Associated Press US", "url": "https://storage.googleapis.com/afs-prod/feeds/usnews.xml"},
    ]
}
SEGMENT_ORDER = ["Top Stories", "Political", "US National"]
KEN_BURNS_EFFECTS = ["x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'", "x='(iw-iw/zoom)':y='(ih-ih/zoom)/2'", "x=0:y='(ih-ih/zoom)/2'", "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)'", "x='(iw-iw/zoom)/2':y=0", "x=0:y=0", "x='iw-iw/zoom':y='ih-ih/zoom'"]


# --- Setup Functions ---
def setup_config():
    global UNSPLASH_API_KEY
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"FATAL: Configuration file '{CONFIG_FILE}' not found.")
        config = configparser.ConfigParser(); config['API_KEYS'] = {'UNSPLASH_ACCESS_KEY': 'YOUR_ACCESS_KEY_HERE'}
        with open(CONFIG_FILE, 'w') as configfile: config.write(configfile)
        logger.error(f"A template config file has been created. Please add your Unsplash API key.")
        return False
    config = configparser.ConfigParser(); config.read(CONFIG_FILE)
    UNSPLASH_API_KEY = config.get('API_KEYS', 'UNSPLASH_ACCESS_KEY', fallback=None)
    if not UNSPLASH_API_KEY or UNSPLASH_API_KEY == "YOUR_ACCESS_KEY_HERE":
        logger.error(f"FATAL: Unsplash API key not found in '{CONFIG_FILE}'."); return False
    logger.info("Unsplash API key loaded successfully.")
    return True

def get_next_segment():
    last_segment = "";
    if os.path.exists(LAST_SEGMENT_FILE):
        with open(LAST_SEGMENT_FILE, 'r') as f: last_segment = f.read().strip()
    try: last_index = SEGMENT_ORDER.index(last_segment)
    except ValueError: last_index = -1
    next_index = (last_index + 1) % len(SEGMENT_ORDER)
    current_segment_name = SEGMENT_ORDER[next_index]
    with open(LAST_SEGMENT_FILE, 'w') as f: f.write(current_segment_name)
    logger.info(f"This run's segment is '{current_segment_name}'.")
    return current_segment_name, SEGMENT_SOURCES[current_segment_name]

def setup_nlp_model():
    global NLP_MODEL
    try:
        NLP_MODEL = spacy.load("en_core_web_sm")
        logger.info("spaCy NLP model loaded successfully.")
        return True
    except OSError:
        logger.error("FATAL: spaCy model 'en_core_web_sm' not found. Run 'python3 -m spacy download en_core_web_sm'"); return False

def load_processed_urls():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, 'r') as f: return {line.strip() for line in f if line.strip()}

def save_processed_urls(new_urls):
    with open(HISTORY_FILE, 'a') as f:
        for url in new_urls: f.write(url + '\n')
    logger.info(f"Saved {len(new_urls)} new URLs to history.")

def setup_font():
    global FONT_PATH
    font_preferences = ["Arial", "Helvetica Neue", "Calibri", "Helvetica", "DejaVu Sans", "Liberation Sans"]
    for font_name in font_preferences:
        try: FONT_PATH = font_manager.findfont(font_name, fallback_to_default=False); return True
        except Exception: pass
    logger.error("FATAL: Could not find any suitable system fonts."); return False

def setup_output_directory(): return tempfile.mkdtemp(prefix="news_video_")

def clean_summary_text(raw_text):
    text = html.unescape(raw_text); text = re.sub('<[^<]+?>', '', text)
    junk_patterns = [r'\[\s*\+\s*video\s*\]', r'(?i)\b(continue reading|read more)\b.*', r'<img.*?>']
    for pattern in junk_patterns: text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    doc = NLP_MODEL(text); sentences = [sent.text.strip() for sent in doc.sents]
    clean_summary = ""
    sentence_count = 0
    for sent in sentences:
        if len(sent) > 20: # Prefer slightly longer, more complete sentences
            clean_summary += sent + " "; sentence_count += 1
            if sentence_count >= 2 and len(clean_summary) > 180: break # Get 2-3 good sentences
            if sentence_count >= 3: break
    return clean_summary.strip()

def scrape_leading_report(processed_urls, limit):
    logger.info("-> Firing up custom scraper for The Leading Report...")
    articles = []; base_url = "https://theleadingreport.com/"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(base_url, wait_until="networkidle", timeout=60000)
            link_elements = page.locator("article h3.entry-title a").all()
            for link_element in link_elements[:limit]:
                href = link_element.get_attribute("href"); title = link_element.inner_text().strip()
                full_url = urljoin(base_url, href)
                if full_url and title and full_url not in processed_urls:
                    article_page = browser.new_page(user_agent=USER_AGENT)
                    try:
                        article_page.goto(full_url, wait_until="domcontentloaded", timeout=45000)
                        p_tags = article_page.locator("div.entry-content p").all()[:3]
                        raw_summary = " ".join([p.inner_text() for p in p_tags])
                        summary = clean_summary_text(raw_summary)
                        if summary:
                            articles.append({"title": title, "link": full_url, "summary": summary})
                            logger.info(f"  -> Scraped: {title[:50]}...")
                    except Exception as e: logger.error(f"     Failed to process article page {full_url}: {e}")
                    finally: article_page.close()
            browser.close()
    except Exception as e: logger.error(f"An error occurred during custom scraping for The Leading Report: {e}")
    return articles

def scrape_news(segment_feeds, processed_urls):
    all_headlines = []; headers = {"User-Agent": USER_AGENT}
    for source in segment_feeds:
        if source.get("type") == "custom":
            all_headlines.extend(scrape_leading_report(processed_urls, 10))
            continue
        try:
            logger.info(f"Scraping {source['name']} (RSS)")
            response = requests.get(source['url'], headers=headers, timeout=15); response.raise_for_status()
            soup = BeautifulSoup(response.content, 'lxml-xml')
            for item in soup.find_all('item', limit=10):
                link = item.find('link').text.strip() if item.find('link') else None
                if link and link not in processed_urls:
                    title = item.find('title').text.strip()
                    desc_tag = item.find('description')
                    if title and desc_tag and desc_tag.text:
                        summary = clean_summary_text(desc_tag.text)
                        if 50 < len(summary) < 600:
                            all_headlines.append({ "title": title, "link": link, "summary": summary })
        except Exception as e: logger.error(f"Failed to scrape RSS feed {source['name']}: {e}")

    unique_headlines = list({item['link']: item for item in all_headlines}.values())
    if not unique_headlines: logger.warning("Could not find any new, unprocessed headlines."); return []
    random.shuffle(unique_headlines)
    return unique_headlines[:HEADLINES_LIMIT]

def search_unsplash_for_image(query):
    logger.info(f"Searching Unsplash for: '{query}'")
    headers = {"Authorization": f"Client-ID {UNSPLASH_API_KEY}"}
    params = {"query": query, "orientation": "portrait", "per_page": 1}
    try:
        response = requests.get("https://api.unsplash.com/search/photos", headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data['results']: return data['results'][0]['urls']['regular']
        else: return None
    except Exception as e: logger.error(f"Unsplash API request failed: {e}"); return None

def create_clip_asset(summary, original_headline, output_path):
    logger.info(f"Creating visual asset for: {original_headline}")
    
    doc = NLP_MODEL(original_headline)
    query_parts = [token.text for token in doc if token.pos_ in ['PROPN', 'NOUN'] and not token.is_stop and len(token.text) > 3]
    query = " ".join(query_parts) if query_parts else original_headline
    image_url = search_unsplash_for_image(query)

    TEXT_AREA_HEIGHT, IMAGE_AREA_HEIGHT = 1100, VIDEO_HEIGHT - 1100
    canvas = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), color='#181818'); draw = ImageDraw.Draw(canvas)
    
    font_headline = ImageFont.truetype(FONT_PATH, 90)
    font_summary = ImageFont.truetype(FONT_PATH, 60)
    
    y_after_headline = draw_multiline_text(draw, original_headline, font_headline, 980, 150, '#FFFFFF')
    draw_multiline_text(draw, summary, font_summary, 950, y_after_headline + 60, '#CCCCCC')
    
    if image_url:
        try:
            image_response = requests.get(image_url, stream=True, timeout=15, headers={'User-Agent': USER_AGENT})
            image_response.raise_for_status()
            article_image = Image.open(image_response.raw).convert("RGB")
            cropped_image = crop_to_fill(article_image, VIDEO_WIDTH, IMAGE_AREA_HEIGHT)
            canvas.paste(cropped_image, (0, TEXT_AREA_HEIGHT)); logger.info(f"Successfully attached image from Unsplash.")
        except Exception as e: logger.error(f"Failed to process image {image_url}: {e}")
    else: logger.warning("Could not find a suitable image from Unsplash for this clip.")
    canvas.save(output_path); return True

async def generate_audio_async(text, output_path):
    communicate = edge_tts.Communicate(text, VOICE); await communicate.save(output_path)

def generate_audio(text, output_path):
    try: asyncio.run(generate_audio_async(text, output_path)); return True
    except Exception as e: logger.error(f"Error generating audio: {e}"); return False

def check_ffmpeg():
    return shutil.which("ffmpeg")

def create_video_clips(news_items, temp_dir):
    clips_data = []
    for i, item in enumerate(news_items):
        original_headline, summary = item['title'], item['summary']
        logger.info(f"--- Processing clip {i+1}/{len(news_items)}: {original_headline[:60]}... ---")
        
        visual_path = os.path.join(temp_dir, f"visual_{i}.png")
        audio_path = os.path.join(temp_dir, f"audio_{i}.mp3")
        
        narration_text = f"{original_headline}. {summary}"
        
        if not create_clip_asset(summary, original_headline, visual_path): continue
        if not generate_audio(narration_text, audio_path): continue
        
        try:
            ffprobe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]
            result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
            audio_duration = float(result.stdout.strip())
            final_duration = max(MIN_CLIP_DURATION, audio_duration + 1.5)
            clips_data.append({"visual_path": visual_path, "audio_path": audio_path, "duration": final_duration, "url": item['link'], "title": original_headline})
        except Exception as e: logger.error(f"Failed to process audio for clip: {e}")
    return clips_data

def create_outro_clip(temp_dir, ffmpeg_path, gif_path):
    outro_audio_path = os.path.join(temp_dir, "outro_audio.mp3")
    outro_image_path = os.path.join(temp_dir, "outro_image.png")
    outro_base_video_path = os.path.join(temp_dir, "outro_base.mp4")
    final_outro_path = os.path.join(temp_dir, "outro_final.mp4")
    outro_duration = 4

    if not generate_audio("Please like and subscribe.", outro_audio_path):
        raise Exception("Failed to generate outro audio.")

    canvas = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), color='#1A1A1A')
    draw = ImageDraw.Draw(canvas)
    font_large = ImageFont.truetype(FONT_PATH, 150)
    draw.text((VIDEO_WIDTH / 2, 400), "LIKE", font=font_large, fill='#FFFFFF', anchor="ms")
    draw.text((VIDEO_WIDTH / 2, 580), "& SUBSCRIBE", font=font_large, fill='#FFFFFF', anchor="ms")
    canvas.save(outro_image_path)

    cmd_base = [ffmpeg_path, '-loop', '1', '-i', outro_image_path, '-i', outro_audio_path, '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', '-t', str(outro_duration), '-y', outro_base_video_path]
    subprocess.run(cmd_base, check=True, capture_output=True, text=True)

    overlay_x, overlay_y = "(W-w)/2", "H/2 - h/2 + 100"
    cmd_overlay = [ffmpeg_path, '-i', outro_base_video_path, '-i', gif_path, '-filter_complex', f"[1:v]scale=450:-1[gif];[0:v][gif]overlay={overlay_x}:{overlay_y}:shortest=1", '-c:a', 'copy', '-y', final_outro_path]
    subprocess.run(cmd_overlay, check=True, capture_output=True, text=True)
    return final_outro_path

def compile_final_video(clips_data, output_path, ffmpeg_path):
    if not clips_data: return False
    temp_dir = os.path.dirname(clips_data[0]["visual_path"])
    concat_list_path = os.path.join(temp_dir, "concat_list.txt")
    clip_files = []
    
    for i, clip in enumerate(clips_data):
        clip_path = os.path.join(temp_dir, f"clip_{i}.mp4")
        duration_frames, chosen_effect = int(clip['duration'] * FPS), random.choice(KEN_BURNS_EFFECTS)
        zoom_level = "1.08"; zoompan_filter = f"scale={VIDEO_WIDTH}*2:-1,zoompan=z='min(zoom+{1/(duration_frames/ (float(zoom_level)-1))},{zoom_level})':d={duration_frames}:{chosen_effect}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS}"
        cmd = [ffmpeg_path, '-i', clip['visual_path'], '-i', clip['audio_path'], '-filter_complex', f"[0:v]{zoompan_filter}[v]", '-map', '[v]', '-map', '1:a', '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-shortest', '-y', clip_path]
        try:
            logger.info(f"Assembling video for clip {i+1}...")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            clip_files.append(clip_path)
        except subprocess.CalledProcessError as e: logger.error(f"Error creating video segment {i}: {e.stderr}"); return False

    with open(concat_list_path, 'w') as f:
        for clip_file in clip_files: f.write(f"file '{os.path.abspath(clip_file)}'\n")

    if os.path.exists(OUTRO_GIF_NAME):
        try:
            logger.info(f"Creating 'Like & Subscribe' outro clip...")
            outro_clip_path = create_outro_clip(temp_dir, ffmpeg_path, OUTRO_GIF_NAME)
            with open(concat_list_path, 'a') as f: f.write(f"file '{os.path.abspath(outro_clip_path)}'\n")
        except Exception as e: logger.error(f"Failed to create outro clip: {e}")
    else: logger.warning(f"Outro GIF '{OUTRO_GIF_NAME}' not found. Skipping outro.")

    final_cmd = [ffmpeg_path, '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c', 'copy', '-y', output_path]
    try:
        subprocess.run(final_cmd, check=True, capture_output=True, text=True)
        logger.info(f"SUCCESS: Final video compiled at: {output_path}")
        return True
    except subprocess.CalledProcessError as e: logger.error(f"FATAL: Error compiling final video: {e.stderr}"); return False

def crop_to_fill(image, target_width, target_height):
    target_ratio = target_width / target_height; image_ratio = image.width / image.height
    if image_ratio > target_ratio:
        new_width = int(target_ratio * image.height); left, right = (image.width - new_width) // 2, (image.width + new_width) // 2; top, bottom = 0, image.height
    else:
        new_height = int(image.width / target_ratio); top, bottom = (image.height - new_height) // 2, (image.height + new_height) // 2; left, right = 0, image.width
    return image.crop((left, top, right, bottom)).resize((target_width, target_height), Image.LANCZOS)
    
def draw_multiline_text(draw, text, font, max_width, start_y, text_color):
    words = text.split(); lines = [""]
    for word in words:
        test_line = (lines[-1] + " " + word).strip()
        if draw.textbbox((0, 0), test_line, font=font)[2] <= max_width: lines[-1] = test_line
        else: lines.append(word)
    y = start_y
    for line in lines:
        if line: draw.text((VIDEO_WIDTH / 2, y), line, font=font, fill=text_color, anchor="ms"); y += font.getbbox("A")[3] * 1.2
    return y
    
def generate_summary_and_hashtags(clips_data, segment_name, output_file):
    logger.info("Generating video description and hashtags...")
    doc = NLP_MODEL(". ".join(clip['title'] for clip in clips_data))
    entities = {ent.text.strip() for ent in doc.ents if ent.label_ in ['PERSON', 'ORG', 'GPE']}
    keywords = {token.text for token in doc if token.pos_ in ['PROPN', 'NOUN'] and not token.is_stop and len(token.text) > 3}
    buzzwords = list(entities.union(keywords)); random.shuffle(buzzwords)
    description = f"Today's {segment_name} News Briefing:\n\n"
    for clip in clips_data: description += f"📌 {clip['title']}\n"
    clean_segment = segment_name.replace(' ', ''); hashtags_set = {f"#{clean_segment}News", "#News", "#DailyNews", "#BreakingNews"}
    for word in buzzwords[:12]:
        clean_word = "".join(part.capitalize() for part in re.split(r'[^A-Z0-9]', word, flags=re.IGNORECASE) if part)
        if clean_word: hashtags_set.add(f"#{clean_word}")
    description += "\n---\n" + " ".join(list(hashtags_set))
    with open(output_file, 'w', encoding='utf-8') as f: f.write(description)
    logger.info(f"Successfully saved description and hashtags to '{output_file}'")
    
def main():
    ffmpeg_path = check_ffmpeg()
    if not setup_config() or not setup_font() or not ffmpeg_path or not setup_nlp_model(): return
    
    current_segment_name, segment_feeds = get_next_segment()
    processed_urls = load_processed_urls()
    temp_dir = None
    try:
        temp_dir = setup_output_directory()
        output_video_path = os.path.join(os.getcwd(), f"news_{current_segment_name.replace(' ', '_')}.mp4")
        news_items = scrape_news(segment_feeds, processed_urls)
        if not news_items: logger.info("No new articles to process. Exiting."); return
        
        clips_data = create_video_clips(news_items, temp_dir)
        if clips_data:
            if compile_final_video(clips_data, output_video_path, ffmpeg_path):
                newly_processed_urls = [clip['url'] for clip in clips_data]
                save_processed_urls(newly_processed_urls)
                generate_summary_and_hashtags(clips_data, current_segment_name, DESCRIPTION_FILE)
        else: logger.error("No valid clips were created. Final video not generated.")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")

if __name__ == "__main__":
    main()
