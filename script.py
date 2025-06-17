import asyncio
import platform
import os
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, concatenate_audioclips, AudioClip
from gtts import gTTS
import json

FPS = 60
LANGUAGE = 'en'  # English language for TTS
IMAGE_PATTERN = "slide_{:02d}.png"  # Matches slide_01.png, slide_02.png, etc.

async def generate_audio(sentences, output_dir="audio"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    for i, sentence in enumerate(sentences, 1):
        tts = gTTS(text=sentence, lang=LANGUAGE, slow=False)
        mp3_file = os.path.join(output_dir, f"audio{i}.mp3")
        wav_file = os.path.join(output_dir, f"audio{i}.wav")
        tts.save(mp3_file)
        # Convert mp3 to wav for better compatibility
        audio = AudioFileClip(mp3_file)
        audio.write_audiofile(wav_file, codec='pcm_s16le')
        print(f"Generated audio for sentence {i}: {sentence}")

async def main():
    # Load JSON file
    with open('story.json', 'r') as file:
        data = json.load(file)
    story = data['story']

    # Generate audio files
    await generate_audio(story)

    # Assume images are named based on IMAGE_PATTERN
    image_files = []
    for i in range(1, len(story) + 1):
        image_path = IMAGE_PATTERN.format(i)
        if os.path.exists(image_path):
            image_files.append(image_path)
        else:
            print(f"Warning: Image {image_path} not found!")
    print(f"Found images: {image_files}")

    audio_clips = []
    video_clips = []

    # Create audio and video clips for each sentence
    for i, sentence in enumerate(story, 1):
        image_path = IMAGE_PATTERN.format(i)
        if os.path.exists(image_path):
            audio_path = f"audio/audio{i}.wav"  # Use .wav instead of .mp3
            if os.path.exists(audio_path):
                audio_clip = AudioFileClip(audio_path).volumex(1.0)  # Ensure volume is not muted
                image_clip = ImageClip(image_path).set_duration(audio_clip.duration)
                video_clips.append(image_clip)
                audio_clips.append(audio_clip)
            else:
                print(f"Warning: Audio file {audio_path} not found!")
        else:
            print(f"Warning: Image {image_path} not found, skipping sentence {i}")

    if not video_clips:
        print("Error: No video clips to concatenate. Check image and audio files.")
        return

    # Synchronize audio with video
    final_video = concatenate_videoclips(video_clips, method="compose")
    final_audio = concatenate_audioclips(audio_clips) if audio_clips else None

    if final_audio:
        final_video = final_video.set_audio(final_audio)

    # Write the final video file with audio-compatible codec
    final_video.write_videofile("cat_story.mp4", fps=FPS, codec="libx264", audio_codec="aac", audio_bitrate="192k")

if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())
