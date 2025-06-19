import os
import logging
import shutil
import tempfile
import re
import subprocess
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from PIL import Image
from gtts import gTTS
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
OUTPUT_DIR = "news_output"
VIDEO_WIDTH, VIDEO_HEIGHT = 1080, 1920  # 9:16 aspect ratio
HEADLINES_LIMIT = 5  # Number of headlines to process
CLIP_DURATION = 5  # Target seconds per clip
MIN_CLIP_DURATION = 3  # Minimum seconds per clip
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15"
]
RSS_SOURCES = [
    {"name": "Reuters", "url": "https://www.reuters.com/arc/outboundfeeds/news-rss/"},
    {"name": "BBC", "url": "http://feeds.bbci.co.uk/news/rss.xml"},
    {"name": "CNN", "url": "http://rss.cnn.com/rss/cnn_topstories.rss"}
]

def setup_output_directory():
    """Create a temporary directory for intermediate files."""
    try:
        temp_dir = tempfile.mkdtemp(prefix="news_scraper_")
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        stat = shutil.disk_usage(temp_dir)
        if stat.free < 1 * 1024 * 1024 * 1024:  # Less than 1GB
            logger.error(f"Insufficient disk space in {temp_dir}: {stat.free / (1024**3):.2f} GB free")
            raise RuntimeError("Insufficient disk space")
        logger.info(f"Created temporary directory: {temp_dir}")
        return temp_dir
    except Exception as e:
        logger.error(f"Failed to create temporary directory: {e}")
        raise

def clean_text(text):
    """Clean text by removing extra whitespace and special characters."""
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[^\w\s.,-]', '', text)
    return text[:100]  # Limit length for brevity

def scrape_news():
    """Scrape latest news headlines and URLs from RSS feeds."""
    news_items = []
    for source in RSS_SOURCES:
        if len(news_items) >= HEADLINES_LIMIT:
            break
        name, url = source["name"], source["url"]
        logger.info(f"Scraping headlines from {name} ({url})")
        
        for user_agent in USER_AGENTS:
            for attempt in range(3):
                try:
                    headers = {"User-Agent": user_agent}
                    response = requests.get(url, headers=headers, timeout=10)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'xml')
                    items = soup.find_all('item', limit=HEADLINES_LIMIT + 5 - len(news_items))
                    for item in items:
                        title = item.find('title')
                        link = item.find('link')
                        if title and link and title.text and link.text:
                            title_text = clean_text(title.text)
                            if title_text and len(news_items) < HEADLINES_LIMIT:
                                news_items.append({"title": title_text, "link": link.text})
                        if len(news_items) >= HEADLINES_LIMIT:
                            break
                    logger.info(f"Scraped {len(news_items)} news items from {name}")
                    break  # Success, move to next source
                except requests.exceptions.HTTPError as e:
                    logger.warning(f"Attempt {attempt + 1} with UA {user_agent} failed for {name}: {e}")
                    if response.status_code == 401:
                        logger.error(f"401 Forbidden for {url}: {response.text[:200]}")
                    if attempt == 2:
                        logger.error(f"Failed to scrape {name} after 3 attempts with UA {user_agent}")
                    continue
                except Exception as e:
                    logger.warning(f"Attempt {attempt + 1} with UA {user_agent} failed for {name}: {e}")
                    if attempt == 2:
                        logger.error(f"Failed to scrape {name} after 3 attempts with UA {user_agent}")
                    continue
            if len(news_items) >= HEADLINES_LIMIT:
                break
    
    logger.info(f"Total scraped {len(news_items)} news items")
    return news_items

def capture_screenshot(url, output_path):
    """Capture a screenshot of a webpage and crop to 9:16 using Playwright."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
            page = browser.new_page()
            page.set_viewport_size({"width": VIDEO_WIDTH * 2, "height": VIDEO_HEIGHT * 2})
            page.set_extra_http_headers({"User-Agent": USER_AGENTS[0]})
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            temp_path = output_path + "_temp.png"
            page.screenshot(path=temp_path)
            browser.close()
        
        img = Image.open(temp_path)
        width, height = img.size
        target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
        current_ratio = width / height
        if current_ratio > target_ratio:
            new_width = int(height * target_ratio)
            left = (width - new_width) // 2
            img = img.crop((left, 0, left + new_width, height))
        else:
            new_height = int(width / target_ratio)
            top = (height - new_height) // 2
            img = img.crop((0, top, width, top + new_height))
        img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
        img.save(output_path)
        os.remove(temp_path)
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Generated screenshot is empty or missing")
        logger.info(f"Screenshot saved: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error capturing screenshot for {url}: {e}")
        return False

def generate_audio(text, output_path):
    """Generate audio from text using gTTS."""
    try:
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(output_path)
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Generated audio file is empty or missing")
        logger.info(f"Audio generated: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error generating audio: {e}")
        return False

def check_ffmpeg():
    """Check if ffmpeg is installed and supports required codecs."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.error("ffmpeg not found in PATH")
        return None, False
    try:
        result = subprocess.run([ffmpeg_path, '-version'], capture_output=True, text=True, check=True)
        logger.info(f"ffmpeg version: {result.stdout.splitlines()[0]}")
        
        result = subprocess.run([ffmpeg_path, '-codecs'], capture_output=True, text=True, check=True)
        codecs = result.stdout
        has_libx264 = 'libx264' in codecs
        has_aac = 'aac' in codecs
        logger.info(f"ffmpeg codecs: libx264={has_libx264}, aac={has_aac}")
        return ffmpeg_path, has_libx264 and has_aac
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg error: {e.stderr}")
        return None, False
    except Exception as e:
        logger.error(f"Error checking ffmpeg: {e}")
        return None, False

def create_video_clips(news_items, output_dir):
    """Create video clips from screenshots and audio, returning clip metadata."""
    clips = []
    for i, item in enumerate(news_items[:HEADLINES_LIMIT]):  # Explicit limit to prevent loops
        screenshot_path = os.path.join(output_dir, f"screenshot_{i}.png")
        audio_path = os.path.join(output_dir, f"audio_{i}.mp3")
        extended_audio_path = os.path.join(output_dir, f"extended_audio_{i}.mp3")
        
        # Capture screenshot
        if not capture_screenshot(item['link'], screenshot_path):
            continue
        
        # Generate audio
        if not generate_audio(item['title'], audio_path):
            continue
        
        # Extend audio with silence if too short
        try:
            audio_duration = float(subprocess.run(
                ['ffprobe', '-i', audio_path, '-show_entries', 'format=duration', '-v', 'quiet', '-of', 'csv=p=0'],
                capture_output=True, text=True, check=True
            ).stdout.strip())
            logger.info(f"Audio {i} duration: {audio_duration:.2f} seconds")
            
            if audio_duration < CLIP_DURATION:
                silence_duration = CLIP_DURATION - audio_duration
                silence_path = os.path.join(output_dir, f"silence_{i}.mp3")
                subprocess.run(
                    ['ffmpeg', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', str(silence_duration), '-y', silence_path],
                    capture_output=True, text=True, check=True
                )
                subprocess.run(
                    ['ffmpeg', '-i', audio_path, '-i', silence_path, '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1', '-y', extended_audio_path],
                    capture_output=True, text=True, check=True
                )
                os.remove(audio_path)
                os.remove(silence_path)
                os.rename(extended_audio_path, audio_path)
                audio_duration = float(subprocess.run(
                    ['ffprobe', '-i', audio_path, '-show_entries', 'format=duration', '-v', 'quiet', '-of', 'csv=p=0'],
                    capture_output=True, text=True, check=True
                ).stdout.strip())
                logger.info(f"Extended audio {i} to {audio_duration:.2f} seconds")
            
            clip_duration = max(audio_duration, MIN_CLIP_DURATION)
            if clip_duration > CLIP_DURATION:
                clip_duration = CLIP_DURATION
            
            clips.append({
                "screenshot_path": screenshot_path,
                "audio_path": audio_path,
                "duration": clip_duration
            })
            logger.info(f"Prepared clip for headline {i+1} with duration {clip_duration:.2f} seconds")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error processing audio for headline {i+1}: {e.stderr}")
            continue
        except Exception as e:
            logger.error(f"Error preparing clip for headline {i+1}: {e}")
            continue
    
    return clips

def compile_video(clips, output_path):
    """Compile video clips into a final video using ffmpeg via subprocess."""
    try:
        ffmpeg_path, supports_codecs = check_ffmpeg()
        if not ffmpeg_path:
            raise RuntimeError("ffmpeg is not properly configured")
        
        if not clips:
            raise ValueError("No valid clips to compile")
        
        temp_dir = os.path.dirname(output_path)
        clip_files = []
        
        # Generate individual clip files
        for i, clip in enumerate(clips):
            clip_path = os.path.join(temp_dir, f"clip_{i}.mp4")
            try:
                vcodec = "libx264" if supports_codecs else "mpeg4"
                acodec = "aac" if supports_codecs else "mp3"
                cmd = [
                    ffmpeg_path,
                    '-loop', '1',
                    '-i', clip['screenshot_path'],
                    '-i', clip['audio_path'],
                    '-c:v', vcodec,
                    '-c:a', acodec,
                    '-pix_fmt', 'yuv420p',
                    '-r', '24',
                    '-b:v', '1000k',
                    '-t', str(clip['duration']),
                    '-y', clip_path
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True
                )
                if result.stderr:
                    logger.warning(f"ffmpeg warning for clip {i+1}: {result.stderr}")
                clip_files.append(clip_path)
                logger.info(f"Generated clip {i+1} at {clip_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"ffmpeg error generating clip {i+1}: {e.stderr}")
                continue
            except Exception as e:
                logger.error(f"Error generating clip {i+1}: {str(e)}")
                continue
        
        if not clip_files:
            raise ValueError("No clips generated successfully")
        
        # Concatenate clips using ffmpeg
        concat_list = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list, 'w') as f:
            for clip_path in clip_files:
                f.write(f"file '{clip_path}'\n")
        
        cmd = [
            ffmpeg_path,
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_list,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-y', output_path
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"ffmpeg concat output: {result.stdout}")
            logger.info(f"Final video saved: {output_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg concat error: {e.stderr}")
            raise
        
        # Clean up individual clip files
        for clip_path in clip_files:
            os.remove(clip_path)
        os.remove(concat_list)
        
        return True
    except Exception as e:
        logger.error(f"Error compiling video: {str(e)}")
        return False

def main():
    """Main function to orchestrate the news video creation."""
    output_dir = setup_output_directory()
    output_video = os.path.join(os.getcwd(), "news_summary.mp4")
    
    try:
        news_items = scrape_news()
        if not news_items:
            logger.error("No news items found. Exiting.")
            return
        
        clips = create_video_clips(news_items, output_dir)
        
        if clips:
            compile_video(clips, output_video)
        else:
            logger.error("No valid clips generated.")
    
    finally:
        try:
            shutil.rmtree(output_dir)
            logger.info(f"Cleaned up temporary directory: {output_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up: {e}")

if __name__ == "__main__":
    main()
