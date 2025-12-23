import os
import time
import requests
import json
import traceback
from dotenv import load_dotenv
from instagrapi import Client
import google.generativeai as genai
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials

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
    """Publishes using Instagram Graph API. Returns True if successful."""
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
    try:
        resp = requests.post(base_url, data=payload)
        result = resp.json()
        
        if 'id' not in result:
            print(f"Error creating container: {result}")
            return False
        
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
                    return False
                
                time.sleep(5)

        print("Publishing container...")
        pub_resp = requests.post(publish_url, data=publish_payload)
        pub_result = pub_resp.json()
        
        if 'id' in pub_result:
            print(f"Successfully published! Post ID: {pub_result['id']}")
            return True
        else:
            print(f"Error publishing: {pub_result}")
            return False
    except Exception as e:
        print(f"Exceptions during publishing: {e}")
        return False

def process_single_link(link):
    """Downloads, analyzes, and reposts a single Instagram link."""
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
            
            success = False
            if public_url:
                # 5. Publish to Instagram via Graph API
                success = publish_to_instagram(public_url, new_caption, media_type)
            else:
                print("Failed to upload to tmpfiles.org")
            
            # Cleanup local file
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                    print(f"Cleaned up {local_path}")
                except:
                    pass
            
            return success
        else:
            print("Caption generation failed.")
    else:
        print("Could not download media.")
    return False

def connect_to_sheet():
    """Connects to Google Sheets using credentials.json."""
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if os.path.exists("credentials.json"):
        try:
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
            client = gspread.authorize(creds)
            return client
        except Exception as e:
            print(f"Error authorizing gspread: {e}")
            return None
    else:
        print("credentials.json not found! Please provide Google Service Account credentials.")
        # Instructions for the user
        print("1. Go to Google Cloud Console.")
        print("2. Create a service account and download the JSON key.")
        print("3. Rename it to 'credentials.json' and place it in this folder.")
        print("4. Share your Google Sheet with the email in the JSON file.")
        return None

def main():
    print("Starting Instagram Bot with Google Sheets integration...")
    
    sheet_id = "14J6W2DysRoAw6BRF2VjyHCldmFZ07vXaSvxSYcEXzRo"
    worksheet_name = "Yashans"
    
    while True:
        client = connect_to_sheet()
        if not client:
            print("Waiting for credentials.json. Retrying in 60 seconds...")
            time.sleep(60)
            continue
            
        try:
            try:
                sheet_obj = client.open_by_key(sheet_id)
            except gspread.exceptions.SpreadsheetNotFound:
                print(f"Error: Spreadsheet with ID '{sheet_id}' not found!")
                time.sleep(60)
                continue
            except (gspread.exceptions.APIError, PermissionError) as e:
                print(f"Error: Permission Denied (403).")
                print("CRITICAL: You MUST share the spreadsheet with this email:")
                print("web-client-1@plenary-net-476220-c9.iam.gserviceaccount.com")
                print("Set the role to 'Editor'.")
                time.sleep(60)
                continue

            sheet = sheet_obj.worksheet(worksheet_name)
            # Get all records (including header)
            rows = sheet.get_all_values()
            
            found_job = False
            for i, row in enumerate(rows):
                if i == 0: continue # Skip header
                
                # columns: url (0), downloaded (1), name (2), Sent-to-Insta (3), runever (4), story (5)
                if len(row) < 5: continue
                
                url = row[0]
                runever = row[4]
                
                if url and not runever: # runever is empty or whitespace
                    print(f"\n--- Processing row {i+1}: {url} ---")
                    found_job = True
                    success = process_single_link(url)
                    
                    if success:
                        print(f"Process successful! Updating row {i+1}...")
                        sheet.update_cell(i + 1, 5, "Yes") # Column 5 is runever
                    else:
                        print(f"Process failed for row {i+1}.")
                    
                    # Wait between posts to avoid rate limits
                    print("Waiting 1 minute before checking next row...")
                    time.sleep(60)
            
            if not found_job:
                print("No new links to process. Checking again in 5 minutes...")
                time.sleep(300)
                
        except Exception as e:
            print(f"Error in main loop: {e}")
            traceback.print_exc()
            time.sleep(60)

if __name__ == "__main__":
    main()
