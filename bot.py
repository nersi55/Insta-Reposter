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
cl.delay_range = [2, 5]

def download_media(link):
    """Downloads media from Instagram link using instagrapi."""
    print(f"Downloading from: {link}")
    try:
        # Load cookies
        if os.path.exists("cookie-insta.json"):
             with open("cookie-insta.json", 'r') as f:
                try:
                    settings = json.load(f)
                    
                    # If it's a full instagrapi settings file
                    if isinstance(settings, dict) and "cookies" in settings:
                        cl.set_settings(settings)
                        print("Settings loaded successfully.")
                    else:
                        # If it's a list of cookies or just a cookie dict
                        cookie_dict = {}
                        if isinstance(settings, list):
                            for c in settings:
                                cookie_dict[c['name']] = c['value']
                        else:
                            cookie_dict = settings
                        
                        # Set cookies on the session
                        cl.set_settings({"cookies": cookie_dict})
                        print("Cookies loaded (via settings) successfully.")
                except Exception as ce:
                    print(f"Could not load cookies: {ce}")
        
        media_pk = cl.media_pk_from_url(link)
        
        # Try different methods to get media info to bypass Pydantic validation errors
        media_info = None
        try:
            print("Fetching media info (v1)...")
            media_info = cl.media_info(media_pk)
        except Exception as e:
            print(f"Standard media_info (v1) failed: {e}")
            
            # Fallback 1: GQL (sometimes more stable with parsing)
            try:
                print("Trying media_info_gql fallback...")
                media_info = cl.media_info_gql(media_pk)
            except Exception as eg:
                print(f"GQL fallback failed: {eg}")
            
            # Fallback 2: a1 (web API)
            if not media_info:
                try:
                    print("Trying web API (a1) fallback...")
                    media_info = cl.media_info_a1(media_pk)
                except Exception as e2:
                    print(f"Web API fallback (a1) also failed: {e2}")

            # Fallback 3: Direct Private Request (Bypass Pydantic Models entirely)
            if not media_info:
                try:
                    print("Trying direct private request to bypass Pydantic models...")
                    info_raw = cl.private_request(f"media/{media_pk}/info/")
                    if 'items' in info_raw and info_raw['items']:
                        item = info_raw['items'][0]
                        # Create a dummy object that mimics media_info structure
                        class DummyInfo:
                            def __init__(self, item):
                                self.media_type = item.get('media_type')
                                self.product_type = item.get('product_type', '')
                                self.user = type('User', (), {'username': item.get('user', {}).get('username')})
                                self.resources = [] # Simplified
                                # For albums
                                if 'carousel_media' in item:
                                    self.resources = [type('Res', (), {'media_type': r.get('media_type')}) for r in item['carousel_media']]
                        
                        media_info = DummyInfo(item)
                        print("Direct request successful (Pydantic bypassed).")
                except Exception as e3:
                    print(f"Direct request fallback failed: {e3}")
            
        if not media_info:
            print("Failed to retrieve media info after all attempts.")
            return None, None, None

        media_type = media_info.media_type
        
        # Get username of original poster
        username = media_info.user.username if media_info.user else None
        
        local_path = None
        if media_type == 1: # Photo
            print("Downloading photo...")
            try:
                local_path = cl.photo_download(media_pk, folder=".")
            except Exception as pe:
                print(f"Photo download failed: {pe}")
                # Try direct URL download
                try:
                    info_raw = cl.private_request(f"media/{media_pk}/info/")
                    if 'items' in info_raw and info_raw['items']:
                        img_url = info_raw['items'][0]['image_versions2']['candidates'][0]['url']
                        local_path = f"{username}_{media_pk}.jpg"
                        response = requests.get(img_url, stream=True)
                        with open(local_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        print(f"Direct photo download successful: {local_path}")
                except Exception as de:
                    print(f"Direct photo download also failed: {de}")
                    return None, None, None
            return str(local_path), "IMAGE", username
            
        elif media_type == 2: # Video/Reel
            print("Downloading video/reel...")
            try:
                if getattr(media_info, 'product_type', '') == "clips":
                    local_path = cl.clip_download(media_pk, folder=".")
                else:
                    local_path = cl.video_download(media_pk, folder=".")
            except Exception as de:
                print(f"Download failed with library method: {de}")
                # Direct download fallback
                try:
                    print("Attempting direct video download from URL...")
                    info_raw = cl.private_request(f"media/{media_pk}/info/")
                    if 'items' in info_raw and info_raw['items']:
                        item = info_raw['items'][0]
                        video_url = None
                        
                        # Try different video URL locations
                        if 'video_versions' in item and item['video_versions']:
                            video_url = item['video_versions'][0]['url']
                        elif 'video_url' in item:
                            video_url = item['video_url']
                        
                        if video_url:
                            local_path = f"{username}_{media_pk}.mp4"
                            print(f"Downloading from direct URL...")
                            response = requests.get(video_url, stream=True)
                            with open(local_path, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            print(f"Direct video download successful: {local_path}")
                        else:
                            print("Could not find video URL in response")
                            return None, None, None
                except Exception as de2:
                    print(f"Direct video download also failed: {de2}")
                    return None, None, None
            return str(local_path), "VIDEO", username
            
        elif media_type == 8: # Album
            print("Downloading album...")
            try:
                paths = cl.album_download(media_pk, folder=".")
                items = []
                for i, p in enumerate(paths):
                    p_str = str(p)
                    # Determine type from resources or extension
                    if media_info.resources and i < len(media_info.resources):
                        r_type = "IMAGE" if media_info.resources[i].media_type == 1 else "VIDEO"
                    else:
                        ext = p_str.lower().split('.')[-1]
                        r_type = "IMAGE" if ext in ['jpg', 'jpeg', 'png'] else "VIDEO"
                    items.append((p_str, r_type))
                return items, "ALBUM", username
            except Exception as ae:
                print(f"Album download failed: {ae}")
                # Direct download for albums
                try:
                    print("Attempting direct album download...")
                    info_raw = cl.private_request(f"media/{media_pk}/info/")
                    if 'items' in info_raw and info_raw['items']:
                        item = info_raw['items'][0]
                        if 'carousel_media' in item:
                            items = []
                            for idx, carousel_item in enumerate(item['carousel_media']):
                                m_type = carousel_item.get('media_type')
                                if m_type == 1:  # Photo
                                    url = carousel_item['image_versions2']['candidates'][0]['url']
                                    local_path = f"{username}_{media_pk}_{idx}.jpg"
                                    r_type = "IMAGE"
                                elif m_type == 2:  # Video
                                    url = carousel_item['video_versions'][0]['url'] if 'video_versions' in carousel_item else None
                                    local_path = f"{username}_{media_pk}_{idx}.mp4"
                                    r_type = "VIDEO"
                                else:
                                    continue
                                
                                if url:
                                    response = requests.get(url, stream=True)
                                    with open(local_path, 'wb') as f:
                                        for chunk in response.iter_content(chunk_size=8192):
                                            f.write(chunk)
                                    items.append((local_path, r_type))
                            print(f"Direct album download successful: {len(items)} items")
                            return items, "ALBUM", username
                except Exception as dae:
                    print(f"Direct album download also failed: {dae}")
                    return None, None, None
        else:
            print(f"Unknown media type: {media_type}")
            return None, None, None

    except Exception as e:
        print(f"Error downloading: {e}")
        # If the error contains HTML/Comet script, it's a login challenge
        if "comet" in str(e).lower() or "script" in str(e).lower():
            print("CRITICAL: Instagram is blocking the request or requiring login/challenge.")
            print("Try refreshing your cookie-insta.json on the server.")
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

def publish_to_instagram(media_data, caption, media_type):
    """Publishes using Instagram Graph API. Supports IMAGE, VIDEO, and ALBUM."""
    print(f"Publishing {media_type} via Graph API...")
    
    base_url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_ACCOUNT_ID}/media"
    
    try:
        if media_type == "ALBUM":
            # media_data is a list of (url, type) tuples
            item_ids = []
            for url, m_t in media_data:
                print(f"Creating item container for {m_t}...")
                item_payload = {
                    'access_token': ACCESS_TOKEN,
                    'is_carousel_item': 'true'
                }
                if m_t == "IMAGE":
                    item_payload['image_url'] = url
                else:
                    item_payload['media_type'] = "VIDEO"
                    item_payload['video_url'] = url
                
                resp = requests.post(base_url, data=item_payload)
                res = resp.json()
                if 'id' not in res:
                    print(f"Error creating carousel item: {res}")
                    return False
                item_ids.append(res['id'])
            
            print(f"Waiting for {len(item_ids)} carousel items to process...")
            time.sleep(15) # Base wait
            
            # Create Carousel Container
            print("Creating carousel container...")
            payload = {
                'access_token': ACCESS_TOKEN,
                'caption': caption,
                'media_type': 'CAROUSEL',
                'children': ','.join(item_ids)
            }
        else:
            # Single Media
            payload = {
                'access_token': ACCESS_TOKEN,
                'caption': caption
            }
            if media_type == "IMAGE":
                payload['image_url'] = media_data
            else: # VIDEO / REELS
                payload['media_type'] = "REELS" 
                payload['video_url'] = media_data
        
        # Step 1: Create Main Container
        resp = requests.post(base_url, data=payload)
        result = resp.json()
        
        if 'id' not in result:
            print(f"Error creating container: {result}")
            return False
        
        creation_id = result['id']
        print(f"Container created ID: {creation_id}")
        
        # Step 2: Wait & Publish
        print("Waiting for media to be ready...")
        time.sleep(10) 
        
        # Check status loop for video or album
        if media_type in ["VIDEO", "ALBUM"]:
            status_url = f"https://graph.facebook.com/v18.0/{creation_id}"
            max_retries = 30
            for _ in range(max_retries):
                status_resp = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN})
                status_data = status_resp.json()
                code = status_data.get('status_code')
                print(f"Processing status: {code}")
                
                if code == 'FINISHED':
                    break
                elif code == 'ERROR':
                    print(f"Error in media processing: {status_data}")
                    return False
                time.sleep(10)

        print("Publishing container...")
        publish_url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_ACCOUNT_ID}/media_publish"
        pub_resp = requests.post(publish_url, data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
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
    """Downloads, analyzes, and reposts a single Instagram link (supports Photo, Video, Album)."""
    # 1. Download media
    media_data, media_type, username = download_media(link)
    
    if not media_data or not media_type:
        print("Could not download media.")
        return False

    print(f"Original poster: @{username}")
    
    try:
        new_caption = None
        if media_type == "ALBUM":
            print(f"Processing album with {len(media_data)} items...")
            # Limit to 10 items for Graph API
            if len(media_data) > 10:
                print("Album too long, limiting to 10 items.")
                media_data = media_data[:10]
            
            # Analyze using the first item of the album
            first_path, first_type = media_data[0]
            new_caption = analyze_media(first_path, first_type, username)
            
            if new_caption:
                print(f"\nGenerated Caption:\n{new_caption}\n")
                print("Auto-reposting Album...")
                
                album_urls = []
                for path, m_t in media_data:
                    processed_path = path
                    if m_t == "VIDEO":
                        processed_path = reencode_video(path)
                    
                    url = upload_to_tmpfiles(processed_path)
                    if url:
                        album_urls.append((url, m_t))
                    else:
                        print(f"Failed to upload item: {path}")
                
                if len(album_urls) > 0:
                    success = publish_to_instagram(album_urls, new_caption, "ALBUM")
                else:
                    print("Failed to upload any album items.")
                    success = False
            else:
                print("Caption generation failed for album.")
                success = False

        else: # IMAGE or VIDEO
            print(f"Downloaded to: {media_data}")
            new_caption = analyze_media(media_data, media_type, username)
            
            if new_caption:
                print(f"\nGenerated Caption:\n{new_caption}\n")
                print("Auto-reposting...")
                
                p_to_upload = media_data
                if media_type == "VIDEO":
                    p_to_upload = reencode_video(media_data)
                
                public_url = upload_to_tmpfiles(p_to_upload)
                if public_url:
                    success = publish_to_instagram(public_url, new_caption, media_type)
                else:
                    print("Failed to upload to tmpfiles.org")
                    success = False
            else:
                print("Caption generation failed.")
                success = False
        
        # Cleanup
        if media_type == "ALBUM":
            for p, _ in media_data:
                if os.path.exists(p):
                    try: os.remove(p); print(f"Cleaned up {p}")
                    except: pass
        else:
            if os.path.exists(media_data):
                try: os.remove(media_data); print(f"Cleaned up {media_data}")
                except: pass
        
        return success

    except Exception as e:
        print(f"Error in process_single_link: {e}")
        traceback.print_exc()
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
                        print(f"Process failed for row {i+1}. Marking as 'No'...")
                        sheet.update_cell(i + 1, 5, "No") # Mark as failed
                    
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
