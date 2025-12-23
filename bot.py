import os
import time
import requests
import json
from dotenv import load_dotenv
from instagrapi import Client
import google.generativeai as genai
from PIL import Image

# Load environment variables
load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# Initialize Instagram Client (for extracting info only)
cl = Client()

def download_media(link):
    """Downloads media from Instagram link using instagrapi."""
    print(f"Downloading from: {link}")
    try:
        # Load cookies
        if os.path.exists("cookie-insta.json"):
             with open("cookie-insta.json", 'r') as f:
                cookies_list = json.load(f)
                cookie_dict = {}
                if isinstance(cookies_list, list):
                    for c in cookies_list:
                        cookie_dict[c['name']] = c['value']
                else:
                    cookie_dict = cookies_list
                
                # set cookies manually
                cl.private.cookies.update(cookie_dict)
                cl.public.cookies.update(cookie_dict)
        
        media_pk = cl.media_pk_from_url(link)
        media_info = cl.media_info(media_pk)
        media_type = media_info.media_type
        
        # Get username of original poster
        username = media_info.user.username if media_info.user else None
        
        # Download the file
        local_path = None
        if media_type == 1: # Photo
            print("Downloading photo...")
            local_path = cl.photo_download(media_pk, folder=".")
            m_type = "IMAGE"
        elif media_type == 2 and media_info.product_type == "clips": # Reel
            print("Downloading reel...")
            local_path = cl.clip_download(media_pk, folder=".")
            m_type = "VIDEO"
        elif media_type == 2: # Video
            print("Downloading video...")
            local_path = cl.video_download(media_pk, folder=".")
            m_type = "VIDEO"
        elif media_type == 8: # Album
             print("Albums not supported in this version.")
             return None, None, None
        
        return local_path, m_type, username

    except Exception as e:
        print(f"Error downloading: {e}")
        return None, None, None

def reencode_video(input_path):
    """Re-encodes video to ensure compatibility with Instagram (H.264 + AAC)."""
    import subprocess
    
    # Convert Path to string if needed
    input_path = str(input_path)
    output_path = input_path.replace('.mp4', '_reencoded.mp4')
    print(f"Re-encoding video for Instagram compatibility...")
    
    try:
        # Instagram prefers: H.264 video codec, AAC audio codec, MP4 container
        cmd = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264',  # Video codec
            '-preset', 'fast',
            '-c:a', 'aac',      # Audio codec
            '-b:a', '128k',     # Audio bitrate
            '-movflags', '+faststart',  # Optimize for streaming
            '-y',  # Overwrite output
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Re-encoding successful!")
            # Remove original and rename
            os.remove(input_path)
            os.rename(output_path, input_path)
            return input_path
        else:
            print(f"Re-encoding failed: {result.stderr}")
            # Return original if re-encoding fails
            return input_path
            
    except FileNotFoundError:
        print("ffmpeg not found. Skipping re-encoding (audio may be lost).")
        print("Install ffmpeg: brew install ffmpeg")
        return input_path
    except Exception as e:
        print(f"Error during re-encoding: {e}")
        return input_path

def upload_to_tmpfiles(file_path):
    """Uploads file to tmpfiles.org and returns public URL."""
    print(f"Uploading {file_path} to tmpfiles.org...")
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post('https://tmpfiles.org/api/v1/upload', files=files)
            result = response.json()
            
            if result.get('status') == 'success':
                # tmpfiles.org returns URL like: https://tmpfiles.org/12345/file.mp4
                # We need the direct download link: https://tmpfiles.org/dl/12345/file.mp4
                url = result['data']['url']
                # Convert to direct download link
                direct_url = url.replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"Upload successful: {direct_url}")
                return direct_url
            else:
                print(f"Upload failed: {result}")
                return None
    except Exception as e:
        print(f"Error uploading to tmpfiles: {e}")
        return None

def analyze_media(file_path, media_type, username=None):
    """Uses Gemini to analyze media and generate caption."""
    print("Analyzing media with Gemini...")
    
    prompt = "You are a social media expert. Analyze this image/video and write an engaging Instagram caption for it in Persian. The caption should be creative, relevant to the visual content, and use appropriate emojis. Do not assume any context other than what is visible. Output ONLY the caption."
    
    try:
        gen_resp = None
        if media_type == "IMAGE":
            img = Image.open(file_path)
            gen_resp = model.generate_content([prompt, img])
        elif media_type == "VIDEO":
            print("Uploading video to Gemini...")
            video_file = genai.upload_file(file_path)
            
            while video_file.state.name == "PROCESSING":
                print('.', end='', flush=True)
                time.sleep(2)
                video_file = genai.get_file(video_file.name)
            
            if video_file.state.name == "FAILED":
                print("Video processing failed.")
                return None
            
            print("Video processed. Generating caption...")
            gen_resp = model.generate_content([prompt, video_file])

        if gen_resp:
            caption = gen_resp.text
            # Add credit if username is available
            if username:
                caption += f"\n\n📸 Credit: @{username}"
            return caption
        return None

    except Exception as e:
        print(f"Error in analysis: {e}")
        return None

def publish_to_instagram(media_url, caption, media_type):
    """Publishes using Instagram Graph API."""
    print("Publishing via Graph API...")
    
    base_url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_ACCOUNT_ID}/media"
    
    payload = {
        'access_token': ACCESS_TOKEN,
        'caption': caption
    }
    
    if media_type == "IMAGE":
        payload['image_url'] = media_url
    else: # VIDEO / REELS
        payload['media_type'] = "REELS" 
        payload['video_url'] = media_url
    
    # Step 1: Create Container
    print("Creating media container...")
    resp = requests.post(base_url, data=payload)
    result = resp.json()
    
    if 'id' not in result:
        print(f"Error creating container: {result}")
        return
    
    creation_id = result['id']
    print(f"Container created ID: {creation_id}")
    
    # Step 2: Publish Container
    publish_url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_ACCOUNT_ID}/media_publish"
    publish_payload = {
        'creation_id': creation_id,
        'access_token': ACCESS_TOKEN
    }
    
    print("Waiting for media to be ready...")
    # Give it a moment for processing (especially videos)
    time.sleep(10) 
    
    # Check status loop for video
    if media_type == "VIDEO":
        status_url = f"https://graph.facebook.com/v18.0/{creation_id}"
        while True:
            status_resp = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN})
            status_data = status_resp.json()
            code = status_data.get('status_code')
            print(f"Processing status: {code}")
            
            if code == 'FINISHED':
                break
            elif code == 'ERROR':
                print("Error in media processing by Instagram.")
                return
            
            time.sleep(5)

    print("Publishing container...")
    pub_resp = requests.post(publish_url, data=publish_payload)
    pub_result = pub_resp.json()
    
    if 'id' in pub_result:
        print(f"Successfully published! Post ID: {pub_result['id']}")
    else:
        print(f"Error publishing: {pub_result}")

def main():
    while True:
        link = input("\nEnter Instagram Link (or 'q' to quit): ")
        if link.lower() == 'q':
            break
        
        # 1. Download media
        local_path, media_type, username = download_media(link)
        
        if local_path and media_type:
            print(f"Downloaded to: {local_path}")
            if username:
                print(f"Original poster: @{username}")
            
            # 2. Analyze with Gemini
            new_caption = analyze_media(local_path, media_type, username)
            
            if new_caption:
                print(f"\nGenerated Caption:\n{new_caption}\n")
                
                # Auto-repost without confirmation
                print("Auto-reposting...")
                
                # 3. Re-encode video if needed (to preserve audio)
                if media_type == "VIDEO":
                    local_path = reencode_video(local_path)
                
                # 4. Upload to tmpfiles.org
                public_url = upload_to_tmpfiles(local_path)
                
                if public_url:
                    # 5. Publish to Instagram via Graph API
                    publish_to_instagram(public_url, new_caption, media_type)
                else:
                    print("Failed to upload to tmpfiles.org")
                
                # Cleanup local file
                if os.path.exists(local_path):
                    os.remove(local_path)
                    print(f"Cleaned up {local_path}")
            else:
                print("Caption generation failed.")
        else:
            print("Could not download media.")

if __name__ == "__main__":
    main()
