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
MIN_CLIP_DURATION = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
FONT_PATH, NLP_MODEL, UNSPLASH_API_KEY = None, None, None
VOICE = "en-US-AriaNeural"
HISTORY_FILE, DESCRIPTION_FILE, LAST_SEGMENT_FILE, CONFIG_FILE = "processed_urls.txt", "video_description.txt", "last_segment.txt", "config.ini"
FPS = 24

# --- Segment-Specific RSS Feeds ---
SEGMENT_SOURCES = {
    "Top Stories": [{"name": "Reuters Top News", "url": "http://feeds.reuters.com/reuters/topNews"}, {"name": "BBC World News", "url": "http://feeds.bbci.co.uk/news/world/rss.xml"}, {"name": "CNN Top Stories", "url": "http://rss.cnn.com/rss/cnn_topstories.rss"}],
    "Technology": [{"name": "TechCrunch", "url": "https://techcrunch.com/feed/"}, {"name": "Wired", "url": "https://www.wired.com/feed/rss"}, {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"}],
    "Finance": [{"name": "Yahoo Finance", "url": "https://finance.yahoo.com/rss/"}, {"name": "MarketWatch", "url": "http://feeds.marketwatch.com/marketwatch/topstories/"}, {"name": "Investopedia", "url": "https://www.investopedia.com/news-rss-4427700"}, {"name": "Reuters Business", "url": "http://feeds.reuters.com/reuters/businessNews"}],
    "Sports": [{"name": "ESPN", "url": "https://www.espn.com/espn/rss/news"}, {"name": "BBC Sport", "url": "http://feeds.bbci.co.uk/sport/rss.xml"}, {"name": "TalkSport", "url": "https://talksport.com/feed"}],
    "Political": [{"name": "Reuters Politics", "url": "http://feeds.reuters.com/reuters/politicsNews"}, {"name": "Politico", "url": "https://rss.politico.com/politico.xml"}, {"name": "The Hill", "url": "https://thehill.com/rss/syndicator/19109"}],
    "Local": [{"name": "New York Times", "url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"}]
}
SEGMENT_ORDER = list(SEGMENT_SOURCES.keys())
KEN_BURNS_EFFECTS = ["x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'", "x='(iw-iw/zoom)':y='(ih-ih/zoom)/2'", "x=0:y='(ih-ih/zoom)/2'", "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)'", "x='(iw-iw/zoom)/2':y=0", "x=0:y=0", "x='iw-iw/zoom':y='ih-ih/zoom'"]


# --- NEW BUZZ GENERATION ---
TOPIC_BASED_TEMPLATES = [
    "Why is everyone suddenly talking about {topic}?",
    "Everything is about to change because of {topic}.",
    "Here's what you're not being told about {topic}.",
    "Could this be the biggest news of the year for {topic}?",
    "Forget everything you knew about {topic}.",
    "This is the real story behind {topic}.",
    "What does this news about {topic} actually mean?"
]

GENERIC_HOOK_TEMPLATES = [
    "Breaking: You need to hear this.",
    "The story is developing right now...",
    "Okay, you're going to want to see this.",
    "This just in, and it's big.",
    "Here’s a story you might have missed.",
    "Wait, what is happening?",
    "You won't believe this new report."
]

def extract_main_subject(headline, nlp_model):
    """Uses NLP to find the most likely subject (topic) of a headline."""
    doc = nlp_model(headline)
    # Prioritize shorter proper noun chunks (e.g., "The White House", "Elon Musk")
    for chunk in doc.noun_chunks:
        # We want concise topics, not entire phrases
        if any(token.pos_ == 'PROPN' for token in chunk) and len(chunk.text.split()) <= 4:
            return chunk.text.strip()
            
    # Fallback to the first single proper noun
    for token in doc:
        if token.pos_ == 'PROPN':
            return token.text
            
    # As a last resort, find the first important noun
    for token in doc:
        if token.pos_ == 'NOUN' and not token.is_stop:
            return token.text
    return None

def generate_buzz_headline(original_headline):
    """Rewrites a formal headline into an engaging, non-repetitive hook."""
    topic = extract_main_subject(original_headline, NLP_MODEL)

    # If we found a good, concise topic, use a topic-based template for a high-quality hook.
    if topic:
        chosen_template = random.choice(TOPIC_BASED_TEMPLATES)
        buzzy_headline = chosen_template.replace("{topic}", topic)
        return " ".join(buzzy_headline.split())
    
    # If no suitable topic was found, fall back to a generic hook to avoid repetition.
    else:
        return random.choice(GENERIC_HOOK_TEMPLATES)

# --- END OF NEW BUZZ GENERATION ---


# --- Setup Functions ---
def setup_config():
    global UNSPLASH_API_KEY
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"FATAL: Configuration file '{CONFIG_FILE}' not found.")
        logger.error("Please create it and add your Unsplash API key. See instructions.")
        return False
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    UNSPLASH_API_KEY = config.get('API_KEYS', 'UNSPLASH_ACCESS_KEY', fallback=None)
    if not UNSPLASH_API_KEY or UNSPLASH_API_KEY == "YOUR_ACCESS_KEY_HERE":
        logger.error(f"FATAL: Unsplash API key not found in '{CONFIG_FILE}'.")
        logger.error("Please get a free key from unsplash.com/developers and add it to the config file.")
        return False
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
    logger.info(f"Last segment was '{last_segment}'. This run's segment is '{current_segment_name}'.")
    return current_segment_name, SEGMENT_SOURCES[current_segment_name]

def setup_nlp_model():
    global NLP_MODEL
    try: NLP_MODEL = spacy.load("en_core_web_sm"); return True
    except OSError: logger.error("FATAL: spaCy model 'en_core_web_sm' not found. Run 'python3 -m spacy download en_core_web_sm'"); return False

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
def clean_text(text): return re.sub(r'\s+', ' ', text).strip()

def scrape_news(segment_feeds, processed_urls):
    all_headlines = []; scrape_limit_per_source = 15; headers = {"User-Agent": USER_AGENT}
    for source in segment_feeds:
        try:
            logger.info(f"Scraping {source['name']}")
            response = requests.get(source['url'], headers=headers, timeout=15); response.raise_for_status()
            soup = BeautifulSoup(response.content, 'xml')
            for item in soup.find_all('item', limit=scrape_limit_per_source):
                link_tag = item.find('link')
                if link_tag and link_tag.text:
                    link = link_tag.text.strip()
                    if link not in processed_urls:
                        title_tag = item.find('title')
                        if title_tag and title_tag.text: all_headlines.append({"title": clean_text(title_tag.text), "link": link})
        except Exception as e: logger.error(f"Failed to scrape {source['name']}: {e}")
    unique_headlines = list({item['link']: item for item in all_headlines}.values())
    if not unique_headlines: logger.warning("Could not find any new, unprocessed headlines."); return []
    random.shuffle(unique_headlines)
    return unique_headlines[:HEADLINES_LIMIT]

def search_unsplash_for_image(query):
    """Fallback function to search for an image on Unsplash."""
    logger.warning(f"Initiating Unsplash API fallback search for query: '{query}'")
    headers = {"Authorization": f"Client-ID {UNSPLASH_API_KEY}"}
    params = {
        "query": query,
        "orientation": "portrait",
        "per_page": 1
    }
    try:
        response = requests.get("https://api.unsplash.com/search/photos", headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data['results']:
            image_url = data['results'][0]['urls']['regular']
            logger.info(f"Success! Found Unsplash image: {image_url}")
            return image_url
        else:
            logger.error(f"Unsplash search for '{query}' yielded no results.")
            return None
    except Exception as e:
        logger.error(f"Unsplash API request failed: {e}"); return None

def create_clip_asset(url, buzzy_headline, original_headline, output_path):
    logger.info(f"Creating visual asset for: {original_headline}")
    image_url = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page.goto(url, wait_until="networkidle", timeout=45000)
            
            og_image_locator = page.locator('meta[property="og:image"]')
            if og_image_locator.count() > 0:
                image_url = og_image_locator.first.get_attribute('content')
                logger.info(f"Success! Found 'og:image': {image_url}")
            else:
                logger.info("og:image not found. Starting on-page search.")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)"); page.wait_for_timeout(1000)
                image_selectors = ['article img', 'main img', '.story-body img', 'figure img']
                for selector in image_selectors:
                    for element in page.locator(selector).all():
                        src = (element.get_attribute('src') or element.get_attribute('data-src'))
                        if src and src.startswith('http'):
                            box = element.bounding_box()
                            if box and box['width'] > 300:
                                image_url = urljoin(page.url, src); logger.info(f"Found hero image via targeted search: {image_url}"); break
                    if image_url: break
            browser.close()
    except Exception as e: logger.warning(f"Playwright failed to get image from {url}: {e}")

    if not image_url:
        logger.error("All on-page scraping methods failed. Using Unsplash API fallback.")
        doc = NLP_MODEL(original_headline)
        query = " ".join([token.text for token in doc if token.pos_ in ['PROPN', 'NOUN'] and not token.is_stop])
        if not query: query = original_headline.split(' ')[0]
        image_url = search_unsplash_for_image(query)

    TEXT_AREA_HEIGHT, IMAGE_AREA_HEIGHT = 800, VIDEO_HEIGHT - 800
    canvas = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), color='#222222'); draw = ImageDraw.Draw(canvas)
    
    font_hook = ImageFont.truetype(FONT_PATH, 90)
    font_reveal = ImageFont.truetype(FONT_PATH, 55)
    
    y_after_hook = draw_multiline_text(draw, buzzy_headline, font_hook, 980, 180, '#FFFFFF')
    draw_multiline_text(draw, original_headline, font_reveal, 950, y_after_hook + 40, '#CCCCCC')
    
    if image_url:
        try:
            image_response = requests.get(image_url, stream=True, timeout=15, headers={'User-Agent': USER_AGENT})
            image_response.raise_for_status()
            article_image = Image.open(image_response.raw).convert("RGB")
            cropped_image = crop_to_fill(article_image, VIDEO_WIDTH, IMAGE_AREA_HEIGHT)
            canvas.paste(cropped_image, (0, TEXT_AREA_HEIGHT)); logger.info("Successfully attached image to visual.")
        except Exception as e: logger.error(f"Failed to process final image {image_url}: {e}")
    else: logger.critical("FATAL: No image could be found from any source for this clip.")
    canvas.save(output_path); return True

async def generate_audio_async(text, output_path):
    communicate = edge_tts.Communicate(text, VOICE); await communicate.save(output_path)

def generate_audio(text, output_path):
    try: asyncio.run(generate_audio_async(text, output_path)); return True
    except Exception as e: logger.error(f"Error generating audio: {e}"); return False

def check_ffmpeg():
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path: logger.error("ffmpeg not found in PATH."); return None
    return ffmpeg_path

def create_video_clips(news_items, temp_dir):
    clips_data = []
    for i, item in enumerate(news_items):
        original_headline = item['title']
        buzzy_headline = generate_buzz_headline(original_headline)
        
        logger.info(f"--- Processing clip {i+1}/{len(news_items)} ---")
        logger.info(f"Original headline: {original_headline}")
        logger.info(f"Buzzy headline:    {buzzy_headline}")
        
        visual_path = os.path.join(temp_dir, f"visual_{i}.png"); audio_path = os.path.join(temp_dir, f"audio_{i}.mp3")
        
        narration_text = f"{buzzy_headline}... {original_headline}"
        
        if not create_clip_asset(item['link'], buzzy_headline, original_headline, visual_path): continue
        if not generate_audio(narration_text, audio_path): continue
        
        try:
            ffprobe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]
            result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
            audio_duration = float(result.stdout.strip())
            final_duration = max(MIN_CLIP_DURATION, audio_duration + 0.5)
            clips_data.append({"visual_path": visual_path, "audio_path": audio_path, "duration": final_duration, "url": item['link'], "title": original_headline})
        except Exception as e: logger.error(f"Failed to process audio for '{original_headline}': {e}")
    return clips_data

def compile_final_video(clips_data, output_path, ffmpeg_path):
    if not clips_data: return False
    temp_dir = os.path.dirname(clips_data[0]["visual_path"]); concat_list_path = os.path.join(temp_dir, "concat_list.txt"); clip_files = []
    for i, clip in enumerate(clips_data):
        clip_path = os.path.join(temp_dir, f"clip_{i}.mp4")
        duration_frames, chosen_effect = int(clip['duration'] * FPS), random.choice(KEN_BURNS_EFFECTS)
        zoom_level = "1.1"; zoompan_filter = f"scale={VIDEO_WIDTH}*2:-1,zoompan=z='min(zoom+{1/(duration_frames/ (float(zoom_level)-1))},{zoom_level})':d={duration_frames}:{chosen_effect}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS}"
        cmd = [ffmpeg_path, '-i', clip['visual_path'], '-i', clip['audio_path'], '-filter_complex', f"[0:v]{zoompan_filter}[v]", '-map', '[v]', '-map', '1:a', '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-shortest', '-y', clip_path]
        try:
            logger.info(f"Applying Ken Burns effect for clip {i+1}...")
            subprocess.run(cmd, check=True, capture_output=True, text=True); clip_files.append(clip_path)
        except subprocess.CalledProcessError as e: logger.error(f"Error creating video segment {i}: {e.stderr}"); return False
    with open(concat_list_path, 'w') as f:
        for clip_file in clip_files: f.write(f"file '{os.path.abspath(clip_file)}'\n")
    final_cmd = [ffmpeg_path, '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c', 'copy', '-y', output_path]
    try:
        subprocess.run(final_cmd, check=True, capture_output=True, text=True); logger.info(f"Final video successfully compiled at: {output_path}"); return True
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
    full_text = ". ".join(clip['title'] for clip in clips_data)
    doc = NLP_MODEL(full_text)
    entities = {ent.text.strip() for ent in doc.ents if ent.label_ in ['PERSON', 'ORG', 'GPE']}
    keywords = {token.text for token in doc if token.pos_ in ['PROPN', 'NOUN'] and not token.is_stop and len(token.text) > 3}
    buzzwords = list(entities.union(keywords)); random.shuffle(buzzwords)
    top_buzzwords = buzzwords[:5]
    description = f"--- {segment_name.upper()} NEWS --- \n\nIn today's {segment_name.lower()} briefing:\n"
    for clip in clips_data: description += f"- {clip['title']}\n"
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
    processed_urls = load_processed_urls()
    temp_dir = None
    try:
        temp_dir = setup_output_directory()
        output_video_path = os.path.join(os.getcwd(), f"news_{current_segment_name.replace(' ', '_')}.mp4")
        news_items = scrape_news(segment_feeds, processed_urls)
        if not news_items: logger.info("No new articles to process. Exiting."); return
        clips_data = create_video_clips(news_items, temp_dir)
        if clips_data:
            if compile_final_video(clips_data, output_video_path, check_ffmpeg()):
                newly_processed_urls = [clip['url'] for clip in clips_data]
                save_processed_urls(newly_processed_urls)
                generate_summary_and_hashtags(clips_data, current_segment_name, DESCRIPTION_FILE)
        else: logger.error("No valid clips created. Final video not generated.")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")

if __name__ == "__main__":
    main()
