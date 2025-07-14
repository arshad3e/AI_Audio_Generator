import os
import glob
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- CONFIGURATION ---
VIDEOS_FOLDER = "videos"
SESSION_DIR = "youtube_session"
HEADLESS_MODE = False
# Delay in milliseconds after selecting Public to ensure the UI is ready.
# 3000ms = 3 seconds.
ACTION_DELAY = 3000

# --- SCRIPT ---
def upload_videos(page):
    """Finds all videos in the 'videos' folder and uploads them."""
    print("Searching for videos...")
    
    video_files = []
    supported_formats = ('*.mp4', '*.mov', '*.avi', '*.mkv')
    for ext in supported_formats:
        video_files.extend(glob.glob(os.path.join(VIDEOS_FOLDER, ext)))

    if not video_files:
        print(f"No video files found in the '{VIDEOS_FOLDER}' folder. Nothing to do.")
        return

    print(f"Found {len(video_files)} video(s) to upload.")

    for video_path in video_files:
        video_title = os.path.basename(video_path)
        print(f"\n--- Starting upload for: {video_title} ---")
        
        try:
            page.goto("https://studio.youtube.com")
            
            page.locator('#create-icon').click()
            page.locator('tp-yt-paper-item[test-id="upload-beta"]').click()

            file_input = page.locator('input[type="file"]')
            file_input.set_input_files(video_path)
            
            print("File selected. Waiting for video details dialog...")
            
            title_input = page.locator('ytcp-social-suggestions-textbox[label="Title"]')
            title_input.wait_for(state="visible", timeout=60000)
            print("Dialog is ready.")

            print("Locating audience selection...")
            not_made_for_kids_radio = page.get_by_role("radio", name="No, it's not made for kids")
            
            not_made_for_kids_radio.scroll_into_view_if_needed()
            
            print("Setting audience to 'No, it's not made for kids'.")
            not_made_for_kids_radio.click()
            
            next_button = page.locator("#next-button")
            for i in range(3):
                next_button.click()
                print(f"Clicked 'Next' ({i+1}/3)")
            
            # --- FINAL PUBLISHING LOGIC ---
            print("Setting visibility to Public.")
            page.locator('tp-yt-paper-radio-button[name="PUBLIC"]').click()
            
            # Wait a few seconds for the UI to stabilize before publishing.
            page.wait_for_timeout(ACTION_DELAY)

            # Use the correct ID for the Publish button from the error log.
            print("Publishing the video...")
            page.locator("#done-button").click()
            # --- END OF LOGIC ---
            
            print("Waiting for final confirmation dialog...")
            page.locator("#close-button").wait_for(state="visible", timeout=3600000)
            print(f"✅ Video '{video_title}' published successfully!")
            
            page.locator("#close-button").click()

        except Exception as e:
            print(f"❌ An error occurred while uploading '{video_title}': {e}")
            page.screenshot(path=f"error_screenshot_{video_title}.png")
            print("Saved an error screenshot for debugging.")
            continue 

def main():
    """Launches the browser and manages the session."""
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=HEADLESS_MODE,
            args=["--disable-blink-features=AutomationControlled"]
        )
        
        page = browser.new_page()
        page.goto("https://studio.youtube.com")
        
        create_button_locator = page.locator("#create-icon")

        try:
            create_button_locator.wait_for(timeout=15000)
            print("✅ Already logged in using saved session.")
        except PlaywrightTimeoutError:
            print("⚠️ Could not find a logged-in session.")
            print("Please log in to your YouTube account in the browser window.")
            print("The script will automatically continue once you are logged in.")
            create_button_locator.wait_for(timeout=300000)
            print("✅ Login successful! Session has been saved for future runs.")
        
        upload_videos(page)
        
        print("\nAll tasks finished.")
        browser.close()

if __name__ == "__main__":
    main()
