import os
import subprocess  # For checking ffmpeg
from google.cloud import texttospeech
from pydub import AudioSegment
from pydub.generators import Sine
from pydub.playback import play

# Path to your service account key JSON file
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'put your json key file here'  # Replace with your actual path


def generate_telugu_voiceover(telugu_text, output_filename="telugu_meditation_voiceover.mp3"):
    """Generates a calm and soothing Telugu voiceover using Google Cloud TTS API,
    handling long text by splitting it into chunks.

    Args:
        telugu_text: The Telugu text to convert to speech.
        output_filename: The name of the output MP3 file.
    """
    try:
        # Check if ffmpeg is installed
        try:
            subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
            print("FFmpeg is installed and accessible.")
        except FileNotFoundError:
            print("Error: FFmpeg is not installed or not in your system's PATH.")
            print("Please follow the instructions at https://github.com/jiaaro/pydub#dependencies to install FFmpeg.")
            return  # Exit if FFmpeg is not found

        # Instantiates a client
        client = texttospeech.TextToSpeechClient()

        # Configure voice and audio (same as before)
        voice = texttospeech.VoiceSelectionParams(
            language_code='te-IN',  # Telugu (India)
            name='te-IN-Standard-A',  # REPLACE WITH A VALID TELUGU VOICE FROM GOOGLE CLOUD. Double check that voice is still there and valid!
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE # Make sure the voice is female
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.85,  # Adjust as needed for best sound
            pitch=-2.0          # Adjust as needed for best sound
        )

        # Split the text into chunks smaller than 5000 bytes (adjust as needed)
        max_chunk_size = 4000  # Reduced max_chunk_size for more buffer
        text_chunks = split_text_into_chunks(telugu_text, max_chunk_size)

        audio_segments = []
        for i, chunk in enumerate(text_chunks):

            ssml_chunk = f'<speak>{chunk}</speak>' #readd now that we have a proper function
            # Set the text input to be synthesized
            synthesis_input = texttospeech.SynthesisInput(ssml=ssml_chunk)  # use ssml instead of text

            # Perform text-to-speech request
            response = client.synthesize_speech(
                input=synthesis_input, voice=voice, audio_config=audio_config
            )

            # Save the audio segment to a file
            segment_filename = f"segment_{i}.mp3"
            with open(segment_filename, 'wb') as out:
                out.write(response.audio_content)
            print(f'Audio segment {i+1} written to file "{segment_filename}"')

            # Load the audio segment using pydub
            audio_segment = AudioSegment.from_mp3(segment_filename)
            audio_segments.append(audio_segment)

        # Concatenate all audio segments
        combined_audio = AudioSegment.empty()
        for segment in audio_segments:
            combined_audio += segment

        # Load background music (replace with your file path)
        try:
            # Ensure the wave file exists locally before attemtping to add background
            background_sound = AudioSegment.from_file("waves_crashing.mp3", format="mp3")

            # Adjust the volume of the background music to be subtle
            background_sound = background_sound - 10  # Make it less negative to increase sound

             # Make background_sound at least as long as combined_audio
            while len(background_sound) < len(combined_audio):
                 background_sound += background_sound #doubling the sound

            # Trim background_sound to match the duration of combined_audio
            background_sound = background_sound[:len(combined_audio)]

            # Apply a fade-in and fade-out to the background sound, and also add some sound in front
            fade_duration = 3000  # 3 seconds
            background_sound = background_sound.fade_in(fade_duration).fade_out(fade_duration)

            # Overlay voiceover on background sound
            combined_audio = combined_audio.overlay(background_sound)

        except FileNotFoundError:
            print("Background music file 'waves_crashing.mp3' not found. Proceeding without background music")

        #Silence of 30 seconds for relaxing time
        silence_duration=30000 #30 seconds
        silent_segment = AudioSegment.silent(duration=silence_duration)

        # Append the audio segment and the loop to the combined audio and export to combine
        combined_audio += silent_segment#Combine audio and silence snippets

        # Export the combined audio to the output file
        combined_audio.export(output_filename, format="mp3")
        print(f'Combined audio written to file "{output_filename}"')

        # Clean up individual segment files (optional)
        for i in range(len(text_chunks)):
            segment_filename = f"segment_{i}.mp3"
            os.remove(segment_filename)
            print(f"Deleted segment file {segment_filename}")

    except Exception as e:
        print(f"Error generating voiceover: {e}")


def split_text_into_chunks(text, max_chunk_size):
    """Splits a string into chunks smaller than max_chunk_size bytes,
    trying to split at sentence boundaries if possible.  Handles sentences longer than max_chunk_size."""
    chunks = []
    current_chunk = ""
    sentences = text.split("।")  # Split at Telugu full stop (। - U+0964)

    for sentence in sentences:
         # Use this for the SSML tags, this step is EXTREMELY IMPORTANT
        sentence = sentence.replace('(4 సెకన్ల పాటు శ్వాసలోకి తీసుకోండి)', '<break time="4s"/>')
        sentence = sentence.replace('(2 సెకన్ల పాటు ఆపి ఉంచండి)', '<break time="2s"/>')
        sentence = sentence.replace('(6 సెకన్ల పాటు ఊపిరి బయటకి వదలండి)', '<break time="6s"/>')
        sentence = sentence.replace('(4 సెకన్ల పాటు)', '<break time="4s"/>') #added this too
        sentence = sentence.replace('(2 సెకన్ల పాటు)', '<break time="2s"/>')#added this too
        sentence = sentence.replace('(6 సెకన్ల పాటు)', '<break time="6s"/>')#added this too

        encoded_sentence = sentence.encode('utf-8')
        sentence_length = len(encoded_sentence)

        print(f"Sentence: '{sentence}', Length (bytes): {sentence_length}")

        if sentence_length < max_chunk_size:  # Sentence fits within the limit
            if len(current_chunk.encode('utf-8')) + sentence_length < max_chunk_size:
                current_chunk += sentence + "।"
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    print(f"Chunk added. Length (bytes): {len(current_chunk.encode('utf-8'))}")
                current_chunk = sentence + "।"
        else:  # Sentence is too long - MUST SPLIT IT
            print(f"Long sentence detected. Splitting further...")
            sub_sentences = split_long_sentence(sentence, max_chunk_size) #Split at smaller intervals

            for sub_sentence in sub_sentences:
                encoded_sub_sentence = sub_sentence.encode('utf-8')
                sub_sentence_length = len(encoded_sub_sentence)

                if len(current_chunk.encode('utf-8')) + sub_sentence_length < max_chunk_size:
                    current_chunk += sub_sentence
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                        print(f"Chunk added. Length (bytes): {len(current_chunk.encode('utf-8'))}")
                    current_chunk = sub_sentence

        if current_chunk:
            chunks.append(current_chunk)
            print(f"Final chunk added. Length (bytes): {len(current_chunk.encode('utf-8'))}")

    return chunks

def split_long_sentence(sentence, max_chunk_size):
     """Splits a long sentence into smaller sub-sentences or phrases."""
     sub_sentences = []
     current_sub_sentence = ""
     words = sentence.split() #split at spaces

     for word in words:
          encoded_word = word.encode('utf-8')
          word_length = len(encoded_word)

          if len(current_sub_sentence.encode('utf-8')) + word_length < max_chunk_size:
               current_sub_sentence += word + " " #Add word and space
          else:
               if current_sub_sentence:
                    sub_sentences.append(current_sub_sentence)
               current_sub_sentence = word + " " #start new sub sentence

     if current_sub_sentence:
          sub_sentences.append(current_sub_sentence)

     return sub_sentences

if __name__ == "__main__":
    telugu_meditation_script = """
స్వాగతం. ఇది మీ సమయం... విశ్రాంతిగా ఉండటానికి, నెమ్మదిగా తీసుకోవడానికి, మరియు కేవలం ఉండటానికి.

మొదట మీరు ఆహ్లాదకరమైన స్థితిలో కూర్చోండి లేదా పడుకోండి. మీ చేతులను మీ తొడలపై లేదా పక్కన ఉంచండి.
నెలవంకలా కళ్లను ముడుచుకుని మెల్లగా మూసుకోండి.

ఇప్పుడొక లోతైన ఊపిరి తీసుకోండి...
(4 సెకన్ల పాటు శ్వాసలోకి తీసుకోండి)
ఒక్క క్షణం ఆపండి...
(2 సెకన్ల పాటు ఆపి ఉంచండి)
మెల్లగా ఊపిరి వదిలేయండి...
(6 సెకన్ల పాటు ఊపిరి బయటకి వదలండి)

ఇంకొకసారి చేద్దాం.
లోతుగా శ్వాస తీసుకోండి…
(4 సెకన్ల పాటు)
ఆపి ఉంచండి…
(2 సెకన్ల పాటు)
మెల్లగా విడిచేయండి…
(6 సెకన్ల పాటు)

ఇప్పుడు మీ శరీరాన్ని పూర్తిగా విశ్రాంతి కలిగించండి.
మీ భుజాలను వదలండి...
మీ దవడను నొప్పించకుండా ఉంచండి…
మీ చేతులను సడలించండి…

ఇప్పుడు మీ శరీరంపై దృష్టి పెట్టండి.
మీ తల మీద ఉన్న ఒత్తిడిని గుర్తించండి… దానిని మెల్లగా వదలండి.
మీ భ్రూవరాలను, కళ్లను సడలించండి.
మీ శ్వాస సహజంగా ప్రవహిస్తుండటాన్ని గమనించండి.
ఇప్పుడు మీ భుజాలు, చేతులు, అరచేతులు పూర్తిగా రిలాక్స్ అవుతున్నాయనుకోండి.

ప్రతి ఊపిరితిత్తిని బయటకి వదిలినప్పుడూ, మీ శరీరం మరింత హాయిగా మారుతోంది.
ఇప్పుడు మీ ఛాతిని గమనించండి—అది పైకి, కిందికి కదులుతున్న రీతిని ఫీలయండి.
మీ కడుపును, నడుమును, కాళ్లను పూర్తిగా రిలాక్స్ చేయండి…

ఇప్పుడు నిశ్శబ్దంగా ఉండండి.
మీ ఆలోచనలు వస్తే, అవి మేఘాల్లా తేలికగా వచ్చి పోతాయని ఊహించండి.
అవును, ఆలోచనలను గుర్తించండి, కానీ వాటిని పట్టుకుని ఉంచుకోవద్దు.

మళ్లీ మీ ఊపిరిపైనే దృష్టి పెట్టండి.
లోతుగా శ్వాస తీసుకోండి…
(4 సెకన్ల పాటు)
ఆపి ఉంచండి…
(2 సెకన్ల పాటు)
మెల్లగా విడిచేయండి…
(6 సెకన్ల పాటు)

ఇలా ఉండటానికి, శ్వాసను ఆస్వాదించడానికి కేవలం ఈ క్షణాన్ని అనుభవించండి.

(30 సెకన్ల పాటు నిశ్శబ్దంగా లేదా తెప్పల శబ్దం, మృదువైన సంగీతం తో)

ఇప్పుడు మీ శరీరంపై మళ్లీ దృష్టి పెట్టండి.
మీ వేళ్లను, మీ కాళ్లను కదపండి.
మీ కింద నేల లేదా కుర్చీ స్పర్శను అనుభవించండి.

ఒక్కసారి లోతుగా ఊపిరి తీసుకోండి…
(4 సెకన్ల పాటు)
ఆపి ఉంచండి…
(2 సెకన్ల పాటు)
మెల్లగా విడిచేయండి…
(6 సెకన్ల పాటు)

ఇప్పుడు మెల్లగా కళ్లను తెరవండి…

మీరు 5 నిమిషాలు పూర్తిగా ప్రశాంతంగా గడిపారు.
ఈ ప్రశాంతతను మీ రోజంతా కొనసాగించండి.
"""

    generate_telugu_voiceover(telugu_meditation_script)
