import os
import logging
import shutil
import tempfile
import re
import subprocess
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from PIL import Image, ImageDraw, ImageFont
# --- FIX 1: ADDED MISSING IMPORTS ---
from urllib.parse import urljoin
from gtts import gTTS

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
CLIP_DURATION = 5
MIN_CLIP_DURATION = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
FONT_PATH = None # This will be set automatically

# --- RSS Sources ---
RSS_SOURCES = [
    # --- FIX 2: UPDATED REUTERS URL ---
    {"name": "Reuters", "url": "http://feeds.reuters.com/reuters/topNews"},
    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/rss.xml"},
    {"name": "CNN", "url": "http://rss.cnn.com/rss/cnn_topstories.rss"}
]

# --- Helper Functions ---

def setup_font():
    """Finds a suitable font on the system automatically."""
    global FONT_PATH
    font_preferences = ["Arial", "Helvetica Neue", "Calibri", "Helvetica", "DejaVu Sans", "Liberation Sans"]
    for font_name in font_preferences:
        try:
            FONT_PATH = font_manager.findfont(font_name, fallback_to_default=False)
            logger.info(f"Successfully found system font: '{font_name}' at {FONT_PATH}")
            return True
        except Exception:
            logger.debug(f"Font '{font_name}' not found, trying next.")
    
    logger.error("FATAL: Could not find any suitable system fonts from the preferred list.")
    return False

def setup_output_directory():
    try:
        temp_dir = tempfile.mkdtemp(prefix="news_video_")
        logger.info(f"Created temporary directory: {temp_dir}")
        return temp_dir
    except Exception as e:
        logger.error(f"Failed to create temporary directory: {e}")
        raise

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

def scrape_news():
    news_items = []
    headers = {"User-Agent": USER_AGENT}
    for source in RSS_SOURCES:
        if len(news_items) >= HEADLINES_LIMIT: break
        try:
            logger.info(f"Scraping headlines from {source['name']}")
            response = requests.get(source['url'], headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'xml')
            for item in soup.find_all('item', limit=HEADLINES_LIMIT):
                title = item.find('title')
                link = item.find('link')
                if title and link and title.text and link.text:
                    news_items.append({"title": clean_text(title.text), "link": link.text.strip()})
                    if len(news_items) >= HEADLINES_LIMIT: break
        except Exception as e:
            logger.error(f"Failed to scrape {source['name']}: {e}")
    logger.info(f"Total scraped {len(news_items)} news items")
    return news_items

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
    lines = []
    current_line = ""
    for word in words:
        if draw.textbbox((0, 0), current_line + " " + word, font=font)[2] <= max_width:
            current_line += " " + word
        else:
            lines.append(current_line.strip())
            current_line = word
    lines.append(current_line.strip())

    y = start_y
    for line in lines:
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
            
            image_selectors = ['article img', 'main img', '.story-body img', 'img[itemprop="image"]']
            for selector in image_selectors:
                elements = page.locator(selector).all()
                for element in elements:
                    src = element.get_attribute('src')
                    if src and (src.startswith('http') or src.startswith('//')):
                        box = element.bounding_box()
                        if box and box.get('width', 0) > 400:
                            image_url = urljoin(page.url, src) # urljoin is now defined
                            logger.info(f"Found suitable image: {image_url}")
                            break
                if image_url: break
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
            image_response = requests.get(image_url, timeout=15, headers={'User-Agent': USER_AGENT})
            image_response.raise_for_status()
            article_image = Image.open(requests.get(image_url, stream=True).raw).convert("RGB")
            cropped_image = crop_to_fill(article_image, VIDEO_WIDTH, IMAGE_AREA_HEIGHT)
            canvas.paste(cropped_image, (0, TEXT_AREA_HEIGHT))
            logger.info("Successfully added image to visual.")
        except Exception as e:
            logger.error(f"Failed to download or process image {image_url}: {e}. Using text-only visual.")

    canvas.save(output_path)
    return True

def generate_audio(text, output_path):
    try:
        tts = gTTS(text=text, lang='en', slow=False) # gTTS is now defined
        tts.save(output_path)
        logger.info(f"Audio generated for: {text}")
        return True
    except Exception as e:
        logger.error(f"Error generating audio: {e}")
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
            final_duration = min(CLIP_DURATION, max(MIN_CLIP_DURATION, audio_duration + 0.5))
            clips_data.append({"visual_path": visual_path, "audio_path": audio_path, "duration": final_duration})
            logger.info(f"Prepared clip for '{item['title']}' with duration {final_duration:.2f}s")
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
        cmd = [
            ffmpeg_path, '-loop', '1', '-i', clip['visual_path'], '-i', clip['audio_path'],
            '-c:v', 'libx264', '-tune', 'stillimage', '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p', '-r', '24', '-shortest', '-t', str(clip['duration']), '-y', clip_path
        ]
        try:
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

    temp_dir = None
    try:
        temp_dir = setup_output_directory()
        output_video_path = os.path.join(os.getcwd(), "news_summary.mp4")
        news_items = scrape_news()
        if not news_items: return
        clips_data = create_video_clips(news_items, temp_dir)
        if clips_data:
            compile_final_video(clips_data, output_video_path, ffmpeg_path)
        else:
            logger.error("No valid clips created. Final video not generated.")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up temporary directory: {temp_dir}")

if __name__ == "__main__":
    main()
