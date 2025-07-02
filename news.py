import os
import logging
import shutil
import tempfile
import re
import subprocess
import requests
import random
import asyncio
import edge_tts
import configparser
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin

# --- Required Libraries Check ---
try:
    import spacy
    from matplotlib import font_manager
except ImportError:
    print("FATAL ERROR: A required library is not installed. Please run 'pip3 install spacy matplotlib edge-tts'")
    print("AND 'python3 -m spacy download en_core_web_sm'")
    exit()

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Constants ---
VIDEO_WIDTH, VIDEO_HEIGHT = 1080, 1920
HEADLINES_LIMIT = 5
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
FONT_PATH, NLP_MODEL, GIPHY_API_KEY, UNSPLASH_API_KEY = None, None, None, None
VOICE = "en-US-AriaNeural"
HISTORY_FILE, DESCRIPTION_FILE, LAST_SEGMENT_FILE, CONFIG_FILE = "processed_urls.txt", "video_description.txt", "last_segment.txt", "config.ini"
FPS = 24

# --- Segment-Specific RSS Feeds ---
SEGMENT_SOURCES = {
    "Top Stories": [{"name": "Reuters Top News", "url": "http://feeds.reuters.com/reuters/topNews"}, {"name": "BBC World News", "url": "http://feeds.bbci.co.uk/news/world/rss.xml"}],
    "Technology": [{"name": "TechCrunch", "url": "https://techcrunch.com/feed/"}, {"name": "Wired", "url": "https://www.wired.com/feed/rss"}],
    "Finance": [{"name": "Yahoo Finance", "url": "https://finance.yahoo.com/rss/"}, {"name": "MarketWatch", "url": "http://feeds.marketwatch.com/marketwatch/topstories/"}],
    "Sports": [{"name": "ESPN", "url": "https://www.espn.com/espn/rss/news"}, {"name": "BBC Sport", "url": "http://feeds.bbci.co.uk/sport/rss.xml"}],
    "Political": [{"name": "Reuters Politics", "url": "http://feeds.reuters.com/reuters/politicsNews"}, {"name": "Politico", "url": "https://rss.politico.com/politico.xml"}]
}
SEGMENT_ORDER = list(SEGMENT_SOURCES.keys())
KEN_BURNS_EFFECTS = ["x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'", "x='(iw-iw/zoom)':y='(ih-ih/zoom)/2'", "x=0:y='(ih-ih/zoom)/2'", "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)'", "x='(iw-iw/zoom)/2':y=0"]


# --- BUZZ GENERATION & SYNC MAPPING ---
HOOK_TEMPLATES = {
    "Why is everyone suddenly talking about {topic}?": "thinking, confused, question mark",
    "Everything is about to change because of {topic}.": "shocked, mind blown, explosion",
    "Here's what you're not being told about {topic}.": "secret, whisper, pointing",
    "This is the real story behind {topic}.": "detective, searching, files",
    "Breaking: You need to hear this.": "breaking news, alert, urgent",
    "The story is developing right now...": "typing, developing, news van",
    "Wait, what is happening?": "wait what, confused, double take"
}

def extract_main_subject(headline, nlp_model):
    doc = nlp_model(headline)
    for chunk in doc.noun_chunks:
        if any(token.pos_ == 'PROPN' for token in chunk) and len(chunk.text.split()) <= 4:
            return chunk.text.strip()
    for token in doc:
        if token.pos_ == 'PROPN': return token.text
    for token in doc:
        if token.pos_ == 'NOUN' and not token.is_stop: return token.text
    return None

def generate_buzz_headline(original_headline):
    topic = extract_main_subject(original_headline, NLP_MODEL)
    templates = list(HOOK_TEMPLATES.keys())
    
    if topic:
        topic_templates = [t for t in templates if "{topic}" in t]
        chosen_template = random.choice(topic_templates)
        hook_text = chosen_template.replace("{topic}", topic)
    else:
        generic_templates = [t for t in templates if "{topic}" not in t]
        chosen_template = random.choice(generic_templates)
        hook_text = chosen_template

    search_term = HOOK_TEMPLATES[chosen_template]
    return hook_text, search_term

# --- Setup Functions ---
def setup_config():
    global GIPHY_API_KEY, UNSPLASH_API_KEY
    if not os.path.exists(CONFIG_FILE): logger.error(f"FATAL: Config file '{CONFIG_FILE}' not found."); return False
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    GIPHY_API_KEY = config.get('API_KEYS', 'GIPHY_API_KEY', fallback=None)
    UNSPLASH_API_KEY = config.get('API_KEYS', 'UNSPLASH_ACCESS_KEY', fallback=None)
    if not GIPHY_API_KEY or GIPHY_API_KEY == "YOUR_GIPHY_KEY_HERE":
        logger.error("FATAL: GIPHY_API_KEY not found in config.ini."); return False
    if not UNSPLASH_API_KEY or UNSPLASH_API_KEY == "YOUR_UNSPLASH_KEY_HERE":
        logger.error("FATAL: UNSPLASH_ACCESS_KEY not found in config.ini."); return False
    logger.info("API keys loaded successfully.")
    return True

def get_next_segment():
    last_segment = ""
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
    try: NLP_MODEL = spacy.load("en_core_web_sm"); return True
    except OSError: logger.error("FATAL: spaCy model 'en_core_web_sm' not found. Run 'python3 -m spacy download en_core_web_sm'"); return False

def setup_font():
    global FONT_PATH
    font_preferences = ["Arial", "Helvetica Neue", "Calibri", "Helvetica", "DejaVu Sans", "Liberation Sans"]
    for font_name in font_preferences:
        try: FONT_PATH = font_manager.findfont(font_name, fallback_to_default=False); return True
        except Exception: pass
    logger.error("FATAL: Could not find any suitable system fonts."); return False

def load_processed_urls():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, 'r') as f: return {line.strip() for line in f if line.strip()}
def save_processed_urls(new_urls):
    with open(HISTORY_FILE, 'a') as f:
        for url in new_urls: f.write(url + '\n')
def setup_output_directory(): return tempfile.mkdtemp(prefix="news_video_")
def clean_text(text): return re.sub(r'\s+', ' ', text).strip()
def check_ffmpeg(): return shutil.which("ffmpeg")

# --- News & Asset Functions ---
def scrape_news(segment_feeds, processed_urls):
    all_headlines = []
    headers = {"User-Agent": USER_AGENT}
    for source in segment_feeds:
        try:
            logger.info(f"Scraping {source['name']}")
            response = requests.get(source['url'], headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'xml')
            for item in soup.find_all('item', limit=15):
                link = item.find('link').text.strip()
                if link not in processed_urls and item.find('title'):
                    all_headlines.append({"title": clean_text(item.find('title').text), "link": link})
        except Exception as e:
            logger.error(f"Failed to scrape {source['name']}: {e}")
    unique_headlines = list({item['link']: item for item in all_headlines}.values())
    random.shuffle(unique_headlines)
    return unique_headlines[:HEADLINES_LIMIT]

def search_giphy_for_gif(query, output_path):
    logger.info(f"Searching GIPHY for '{query}'")
    params = {"api_key": GIPHY_API_KEY, "q": query, "limit": 5, "rating": "pg-13"}
    try:
        response = requests.get("https://api.giphy.com/v1/gifs/search", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data['data']:
            gif_data = random.choice(data['data'])
            mp4_url = gif_data['images']['original_mp4']['mp4']
            gif_response = requests.get(mp4_url, timeout=20)
            gif_response.raise_for_status()
            with open(output_path, 'wb') as f: f.write(gif_response.content)
            return True
    except Exception as e: logger.error(f"GIPHY search failed: {e}")
    return False

def search_unsplash_for_image(query, output_path):
    logger.info(f"Searching Unsplash for '{query}'")
    headers = {"Authorization": f"Client-ID {UNSPLASH_API_KEY}"}
    params = {"query": query, "orientation": "portrait", "per_page": 1}
    try:
        response = requests.get("https://api.unsplash.com/search/photos", headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data['results']:
            image_url = data['results'][0]['urls']['regular']
            img_response = requests.get(image_url, timeout=20)
            img_response.raise_for_status()
            with open(output_path, 'wb') as f: f.write(img_response.content)
            return True
    except Exception as e: logger.error(f"Unsplash search failed: {e}")
    return False

async def generate_audio_async(text, output_path):
    communicate = edge_tts.Communicate(text, VOICE); await communicate.save(output_path)

def get_audio_duration(audio_path):
    ffprobe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]
    duration_str = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True).stdout.strip()
    return float(duration_str)

def draw_multiline_text(draw, text, font, max_width, start_y, text_color):
    words = text.split(); lines = [""]
    for word in words:
        test_line = (lines[-1] + " " + word).strip()
        if draw.textbbox((0, 0), test_line, font=font)[2] <= max_width: lines[-1] = test_line
        else: lines.append(word)
    y = start_y
    for line in lines:
        if line:
            draw.text((VIDEO_WIDTH / 2, y), line, font=font, fill=text_color, anchor="ms")
            y += font.getbbox("A")[3] * 1.2
    return y

# --- VIDEO COMPOSITION ---
def get_reveal_background_video(url, headline, duration, temp_dir, part_name):
    logger.info(f"Getting reveal background for: {headline}")
    image_path = os.path.join(temp_dir, f"bg_image_{part_name}.png")
    image_found = False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=30000)
            og_image = page.locator('meta[property="og:image"]').get_attribute('content')
            if og_image:
                img_response = requests.get(og_image, timeout=15)
                if img_response.ok:
                    with open(image_path, 'wb') as f: f.write(img_response.content)
                    image_found = True
                    logger.info("Found background via og:image tag.")
    except Exception as e:
        logger.warning(f"Playwright failed to get og:image: {e}")

    if not image_found:
        query = extract_main_subject(headline, NLP_MODEL) or headline
        if not search_unsplash_for_image(query, image_path):
             logger.error("All image sources failed. Using a black background.")
             Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), color='black').save(image_path)
    
    # Convert the static image to a video of the required duration
    output_video_path = os.path.join(temp_dir, f"bg_video_{part_name}.mp4")
    cmd = [
        check_ffmpeg(), '-y', '-loop', '1', '-i', image_path,
        '-c:v', 'libx264', '-t', str(duration), '-pix_fmt', 'yuv420p',
        '-vf', f'scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}', output_video_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_video_path

def create_video_part(bg_path, audio_path, text_content, temp_dir, part_name, type_effect=False):
    logger.info(f"Creating video part: {part_name} (Typing: {type_effect})")
    duration = get_audio_duration(audio_path)
    font_size = 100 if type_effect else 70
    font = ImageFont.truetype(FONT_PATH, font_size)
    
    # Animate text
    anim_dir = os.path.join(temp_dir, f"anim_{part_name}")
    os.makedirs(anim_dir, exist_ok=True)
    words = text_content.split()
    total_frames = int(duration * FPS)
    frames_per_word = max(1, int((duration * FPS * 0.8) / len(words))) if type_effect else total_frames

    frame_count = 0
    for i in range(len(words) if type_effect else 1):
        current_text = " ".join(words[:i+1]) if type_effect else text_content
        canvas = Image.new('RGBA', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw_multiline_text(draw, current_text, font, 1000, 250, '#FFFFFF')
        frame_path = os.path.join(anim_dir, f"frame_{frame_count:04d}.png")
        canvas.save(frame_path)
        last_frame_path = frame_path
        
        for _ in range(frames_per_word):
            if frame_count >= total_frames: break
            if frame_count > i * frames_per_word: # Avoid re-saving the first frame
                shutil.copy(last_frame_path, os.path.join(anim_dir, f"frame_{frame_count:04d}.png"))
            frame_count += 1

    while frame_count < total_frames:
        shutil.copy(last_frame_path, os.path.join(anim_dir, f"frame_{frame_count:04d}.png"))
        frame_count += 1
    
    text_video_path = os.path.join(temp_dir, f"text_{part_name}.mov")
    cmd_text = [check_ffmpeg(), '-y', '-framerate', str(FPS), '-i', os.path.join(anim_dir, 'frame_%04d.png'),
                '-c:v', 'qtrle', '-pix_fmt', 'argb', '-an', text_video_path]
    subprocess.run(cmd_text, check=True, capture_output=True)

    # Determine visual filter (Ken Burns for static, simple scale for GIF)
    if type_effect: # It's a GIF
        vf = f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1"
    else: # It's a static image, apply Ken Burns
        chosen_effect = random.choice(KEN_BURNS_EFFECTS)
        zoom_level = "1.1"
        vf = f"scale={VIDEO_WIDTH}*2:-1,zoompan=z='min(zoom+{1/(total_frames/(float(zoom_level)-1))},{zoom_level})':d={total_frames}:{chosen_effect}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS},setsar=1"

    # Compile part
    output_path = os.path.join(temp_dir, f"{part_name}.mp4")
    cmd_compile = [
        check_ffmpeg(), '-y', '-i', bg_path, '-i', text_video_path, '-i', audio_path,
        '-filter_complex', f"[0:v]{vf}[bg];[bg][1:v]overlay=x=0:y=0:shortest=1[v]",
        '-map', '[v]', '-map', '2:a', '-t', str(duration), '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p', '-r', str(FPS), output_path
    ]
    subprocess.run(cmd_compile, check=True, capture_output=True)
    return output_path

def create_video_clips(news_items, temp_dir):
    clip_parts = []
    processed_items = []
    for i, item in enumerate(news_items):
        try:
            original_headline = item['title']
            hook_text, hook_search_term = generate_buzz_headline(original_headline)
            logger.info(f"--- Processing clip {i+1}/{len(news_items)}: {original_headline} ---")

            # --- HOOK PHASE (GIF background) ---
            hook_audio_path = os.path.join(temp_dir, f"audio_{i}_hook.mp3")
            asyncio.run(generate_audio_async(hook_text, hook_audio_path))
            hook_gif_path = os.path.join(temp_dir, f"bg_{i}_hook.mp4")
            if not search_giphy_for_gif(hook_search_term, hook_gif_path): continue
            hook_part_path = create_video_part(hook_gif_path, hook_audio_path, hook_text, temp_dir, f"part_{i}_hook", type_effect=True)

            # --- REVEAL PHASE (Image background) ---
            reveal_audio_path = os.path.join(temp_dir, f"audio_{i}_reveal.mp3")
            asyncio.run(generate_audio_async(original_headline, reveal_audio_path))
            reveal_duration = get_audio_duration(reveal_audio_path)
            reveal_bg_video_path = get_reveal_background_video(item['link'], original_headline, reveal_duration, temp_dir, f"part_{i}_reveal")
            reveal_part_path = create_video_part(reveal_bg_video_path, reveal_audio_path, original_headline, temp_dir, f"part_{i}_reveal", type_effect=False)

            clip_parts.extend([hook_part_path, reveal_part_path])
            processed_items.append(item)
        except Exception as e:
            logger.error(f"Failed to create clip for '{item['title']}': {e}", exc_info=True)
    return clip_parts, processed_items

def compile_final_video(clip_parts, output_path, ffmpeg_path):
    if not clip_parts: return False
    temp_dir = os.path.dirname(clip_parts[0])
    concat_list_path = os.path.join(temp_dir, "concat_list.txt")
    
    with open(concat_list_path, 'w') as f:
        for part_path in clip_parts:
            f.write(f"file '{os.path.abspath(part_path)}'\n")

    final_cmd = [ffmpeg_path, '-y', '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c', 'copy', output_path]
    try:
        subprocess.run(final_cmd, check=True, capture_output=True, text=True)
        logger.info(f"Final video successfully compiled at: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FATAL: Error compiling final video: {e.stderr}")
        return False

def generate_summary_and_hashtags(processed_items, segment_name, output_file):
    logger.info("Generating video description and hashtags...")
    full_text = ". ".join(clip['title'] for clip in processed_items)
    doc = NLP_MODEL(full_text)
    entities = {ent.text.strip() for ent in doc.ents if ent.label_ in ['PERSON', 'ORG', 'GPE']}
    keywords = {token.text for token in doc if token.pos_ in ['PROPN', 'NOUN'] and not token.is_stop and len(token.text) > 3}
    buzzwords = list(entities.union(keywords)); random.shuffle(buzzwords)
    top_buzzwords = buzzwords[:5]
    description = f"--- {segment_name.upper()} NEWS --- \n\nIn today's {segment_name.lower()} briefing:\n"
    for clip in processed_items: description += f"- {clip['title']}\n"
    if top_buzzwords: description += f"\nTune in for the latest on {', '.join(top_buzzwords)} and more."
    clean_segment = segment_name.replace(' ', ''); hashtags_set = {f"#{clean_segment}", "#News", f"#{clean_segment}News"}
    for word in buzzwords[:10]:
        clean_word = "".join(part.capitalize() for part in re.split(r'[^A-Z0-9]', word, flags=re.IGNORECASE) if part)
        if clean_word: hashtags_set.add(f"#{clean_word}")
    hashtags = "\n\n--- HASHTAGS ---\n\n" + " ".join(list(hashtags_set))
    with open(output_file, 'w', encoding='utf-8') as f: f.write(description + hashtags)
    logger.info(f"Successfully saved description and hashtags to '{output_file}'")
    
def main():
    if not setup_config() or not setup_font() or not check_ffmpeg() or not setup_nlp_model(): return
    current_segment_name, segment_feeds = get_next_segment()
    all_processed_urls = load_processed_urls()
    temp_dir = None
    try:
        temp_dir = setup_output_directory()
        output_video_path = os.path.join(os.getcwd(), f"news_{current_segment_name.replace(' ', '_')}.mp4")
        news_items = scrape_news(segment_feeds, all_processed_urls)
        if not news_items:
            logger.info("No new articles to process. Exiting.")
            return
            
        clip_parts, processed_items = create_video_clips(news_items, temp_dir)
        
        if clip_parts:
            if compile_final_video(clip_parts, output_video_path, check_ffmpeg()):
                newly_processed_urls = [item['link'] for item in processed_items]
                save_processed_urls(newly_processed_urls)
                generate_summary_and_hashtags(processed_items, current_segment_name, DESCRIPTION_FILE)
        else:
            logger.error("No valid clips created. Final video not generated.")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")

if __name__ == "__main__":
    main()
