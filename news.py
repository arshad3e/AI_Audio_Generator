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
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PIL import Image, ImageDraw, ImageFont
from urllib.parse import urljoin

# --- New Requirement: This script now requires the matplotlib library ---
# --- Please run: pip3 install matplotlib (if you haven't already) ---
try:
    from matplotlib import font_manager
except ImportError:
    print("FATAL ERROR: The 'matplotlib' library is not installed.")
    print("Please run 'pip3 install matplotlib' in your terminal to continue.")
    exit()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Constants ---
VIDEO_WIDTH, VIDEO_HEIGHT = 1080, 1920
HEADLINES_LIMIT = 5
MIN_CLIP_DURATION = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
FONT_PATH = None
VOICE = "en-US-AriaNeural"
HISTORY_FILE = "processed_urls.txt"
FPS = 24 # Frames per second for the video

# --- Ken Burns Effect Variations ---
# Each string is a different pan/zoom effect for ffmpeg's zoompan filter.
# 'iw' and 'ih' are input width and height. 'on' is the output frame number.
KEN_BURNS_EFFECTS = [
    # Zoom in, centered
    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # Zoom in, pan right
    "x='(iw-iw/zoom)':y='(ih-ih/zoom)/2'",
    # Zoom in, pan left
    "x=0:y='(ih-ih/zoom)/2'",
    # Zoom in, pan down
    "x='(iw-iw/zoom)/2':y='(ih-ih/zoom)'",
    # Zoom in, pan up
    "x='(iw-iw/zoom)/2':y=0",
    # Zoom in, pan to top-left
    "x=0:y=0",
    # Zoom in, pan to bottom-right
    "x='iw-iw/zoom':y='ih-ih/zoom'"
]

# --- RSS Sources ---
RSS_SOURCES = [
    {"name": "Reuters", "url": "http://feeds.reuters.com/reuters/topNews"},
    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/rss.xml"},
    {"name": "CNN", "url": "http://rss.cnn.com/rss/cnn_topstories.rss"}
]

# --- Helper Functions (No changes in these) ---

def load_processed_urls():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, 'r') as f:
        return {line.strip() for line in f if line.strip()}

def save_processed_urls(new_urls):
    with open(HISTORY_FILE, 'a') as f:
        for url in new_urls: f.write(url + '\n')
    logger.info(f"Saved {len(new_urls)} new URLs to history.")

def setup_font():
    global FONT_PATH
    font_preferences = ["Arial", "Helvetica Neue", "Calibri", "Helvetica", "DejaVu Sans", "Liberation Sans"]
    for font_name in font_preferences:
        try:
            FONT_PATH = font_manager.findfont(font_name, fallback_to_default=False)
            logger.info(f"Successfully found system font: '{font_name}'")
            return True
        except Exception: pass
    logger.error("FATAL: Could not find any suitable system fonts.")
    return False

def setup_output_directory():
    return tempfile.mkdtemp(prefix="news_video_")

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def scrape_news(processed_urls):
    all_headlines = []
    scrape_limit_per_source = 15
    headers = {"User-Agent": USER_AGENT}
    for source in RSS_SOURCES:
        try:
            logger.info(f"Scraping headlines from {source['name']}")
            response = requests.get(source['url'], headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'xml')
            for item in soup.find_all('item', limit=scrape_limit_per_source):
                link_tag = item.find('link')
                if link_tag and link_tag.text:
                    link = link_tag.text.strip()
                    if link not in processed_urls:
                        title_tag = item.find('title')
                        if title_tag and title_tag.text:
                            all_headlines.append({"title": clean_text(title_tag.text), "link": link})
        except Exception as e:
            logger.error(f"Failed to scrape {source['name']}: {e}")
    unique_headlines = list({item['link']: item for item in all_headlines}.values())
    if not unique_headlines:
        logger.warning("Could not find any new, unprocessed headlines.")
        return []
    random.shuffle(unique_headlines)
    return unique_headlines[:HEADLINES_LIMIT]

def crop_to_fill(image, target_width, target_height):
    target_ratio = target_width / target_height
    image_ratio = image.width / image.height
    if image_ratio > target_ratio:
        new_width = int(target_ratio * image.height)
        left, right = (image.width - new_width) // 2, (image.width + new_width) // 2
        top, bottom = 0, image.height
    else:
        new_height = int(image.width / target_ratio)
        top, bottom = (image.height - new_height) // 2, (image.height + new_height) // 2
        left, right = 0, image.width
    return image.crop((left, top, right, bottom)).resize((target_width, target_height), Image.LANCZOS)

def draw_multiline_text(draw, text, font, max_width, start_y, text_color):
    words = text.split()
    lines = [""]
    for word in words:
        test_line = (lines[-1] + " " + word).strip()
        if draw.textbbox((0, 0), test_line, font=font)[2] <= max_width:
            lines[-1] = test_line
        else:
            lines.append(word)
    y = start_y
    for line in lines:
        if line:
            draw.text((VIDEO_WIDTH / 2, y), line, font=font, fill=text_color, anchor="ms")
            y += font.getbbox("A")[3] * 1.2
    return y

def create_clip_asset(url, headline, output_path):
    logger.info(f"Creating visual asset for: {headline}")
    image_url = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            page.wait_for_timeout(1500)
            image_selectors = ['article img', 'main img', '.story-body img', 'img[itemprop="image"]']
            for selector in image_selectors:
                elements = page.locator(selector).all()
                for element in elements:
                    src = (element.get_attribute('srcset') or 
                           element.get_attribute('data-src') or 
                           element.get_attribute('src'))
                    if src:
                        image_url = urljoin(page.url, src.split(',')[0].split(' ')[0])
                        logger.info(f"Found hero image via targeted search: {image_url}")
                        break
                if image_url: break
            if not image_url:
                logger.warning("Targeted search failed. Falling back to find largest image on page.")
                all_images = page.locator('img').all()
                max_area = 0
                best_url = None
                for img in all_images:
                    try:
                        box = img.bounding_box()
                        if box and box['width'] > 200 and box['height'] > 200:
                            area = box['width'] * box['height']
                            if area > max_area:
                                max_area = area
                                src = img.get_attribute('src')
                                if src:
                                    best_url = urljoin(page.url, src)
                    except Exception: continue
                if best_url:
                    image_url = best_url
                    logger.info(f"Found largest image via fallback: {image_url}")
            browser.close()
    except Exception as e:
        logger.warning(f"Playwright failed to get image from {url}: {e}. Proceeding without image.")

    TEXT_AREA_HEIGHT = 800
    IMAGE_AREA_HEIGHT = VIDEO_HEIGHT - TEXT_AREA_HEIGHT
    canvas = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), color='#222222')
    draw = ImageDraw.Draw(canvas)
    font_headline = ImageFont.truetype(FONT_PATH, 90)
    draw_multiline_text(draw, headline, font_headline, 980, 250, '#FFFFFF')
    
    if image_url:
        try:
            image_response = requests.get(image_url, stream=True, timeout=15, headers={'User-Agent': USER_AGENT})
            image_response.raise_for_status()
            article_image = Image.open(image_response.raw).convert("RGB")
            cropped_image = crop_to_fill(article_image, VIDEO_WIDTH, IMAGE_AREA_HEIGHT)
            canvas.paste(cropped_image, (0, TEXT_AREA_HEIGHT))
            logger.info("Successfully attached image to visual.")
        except Exception as e:
            logger.error(f"Failed to process image {image_url}: {e}. Using text-only visual.")
    else:
        logger.error("All attempts to find an image failed. Creating text-only slide.")

    canvas.save(output_path)
    return True

async def generate_audio_async(text, output_path):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)

def generate_audio(text, output_path):
    logger.info(f"Generating high-quality audio for: {text}")
    try:
        asyncio.run(generate_audio_async(text, output_path))
        return True
    except Exception as e:
        logger.error(f"Error generating audio with edge-tts: {e}")
        return False

def check_ffmpeg():
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.error("ffmpeg not found in PATH. Please install and add to system PATH.")
    return ffmpeg_path

def create_video_clips(news_items, temp_dir):
    clips_data = []
    for i, item in enumerate(news_items):
        logger.info(f"--- Processing clip {i+1}/{len(news_items)}: {item['title']} ---")
        visual_path = os.path.join(temp_dir, f"visual_{i}.png")
        audio_path = os.path.join(temp_dir, f"audio_{i}.mp3")
        if not create_clip_asset(item['link'], item['title'], visual_path): continue
        if not generate_audio(item['title'], audio_path): continue
        try:
            ffprobe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path]
            result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, check=True)
            audio_duration = float(result.stdout.strip())
            final_duration = max(MIN_CLIP_DURATION, audio_duration + 0.5)
            clips_data.append({"visual_path": visual_path, "audio_path": audio_path, "duration": final_duration, "url": item['link']})
            logger.info(f"Prepared clip with dynamic duration {final_duration:.2f}s")
        except Exception as e:
            logger.error(f"Failed to process audio for '{item['title']}': {e}")
    return clips_data

def compile_final_video(clips_data, output_path, ffmpeg_path):
    if not clips_data:
        logger.error("No clips were generated to compile.")
        return False
        
    temp_dir = os.path.dirname(clips_data[0]["visual_path"])
    concat_list_path = os.path.join(temp_dir, "concat_list.txt")
    clip_files = []

    for i, clip in enumerate(clips_data):
        clip_path = os.path.join(temp_dir, f"clip_{i}.mp4")
        
        # --- THIS IS THE MAJOR CHANGE ---
        # We now build a complex ffmpeg filter to create the Ken Burns effect.
        
        duration_frames = int(clip['duration'] * FPS)
        chosen_effect = random.choice(KEN_BURNS_EFFECTS)
        
        # A slow zoom from 1.0x to 1.1x over the clip's duration
        zoom_level = "1.1" 
        
        # Build the zoompan filter string
        zoompan_filter = (
            f"scale={VIDEO_WIDTH}*2:-1,"
            f"zoompan=z='min(zoom+{1/(duration_frames/ (float(zoom_level)-1))},{zoom_level})':"
            f"d={duration_frames}:{chosen_effect}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={FPS}"
        )
        
        cmd = [
            ffmpeg_path,
            '-i', clip['visual_path'],
            '-i', clip['audio_path'],
            '-filter_complex', f"[0:v]{zoompan_filter}[v]",
            '-map', '[v]',
            '-map', '1:a',
            '-c:v', 'libx264',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-r', str(FPS),
            '-shortest',
            '-y', clip_path
        ]
        
        try:
            logger.info(f"Applying Ken Burns effect for clip {i+1}...")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            clip_files.append(clip_path)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error creating video segment {i}: {e.stderr}")
            return False
            
    with open(concat_list_path, 'w') as f:
        for clip_file in clip_files:
            f.write(f"file '{os.path.abspath(clip_file)}'\n")

    final_cmd = [ffmpeg_path, '-f', 'concat', '-safe', '0', '-i', concat_list_path, '-c', 'copy', '-y', output_path]
    try:
        subprocess.run(final_cmd, check=True, capture_output=True, text=True)
        logger.info(f"Final video successfully compiled at: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FATAL: Error compiling final video: {e.stderr}")
        return False

def main():
    if not setup_font(): return
    ffmpeg_path = check_ffmpeg()
    if not ffmpeg_path: return
    processed_urls = load_processed_urls()
    temp_dir = None
    try:
        temp_dir = setup_output_directory()
        output_video_path = os.path.join(os.getcwd(), "news_summary.mp4")
        news_items = scrape_news(processed_urls)
        if not news_items: 
            logger.info("No new articles to process. Exiting.")
            return
        clips_data = create_video_clips(news_items, temp_dir)
        if clips_data:
            if compile_final_video(clips_data, output_video_path, ffmpeg_path):
                newly_processed_urls = [clip['url'] for clip in clips_data]
                save_processed_urls(newly_processed_urls)
        else:
            logger.error("No valid clips created. Final video not generated.")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")

if __name__ == "__main__":
    main()
