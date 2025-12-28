import os
import time
import requests
import json
import traceback
import re
import warnings
from dotenv import load_dotenv
from instagrapi import Client
# Suppress FutureWarning for deprecated google.generativeai
warnings.filterwarnings('ignore', category=FutureWarning, message='.*google.generativeai.*')
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

# Load environment variables
load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_ACCOUNT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
POST_INTERVAL_MINUTES = int(os.getenv("POST_INTERVAL_MINUTES", "1"))  # Default: 1 minute

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# Initialize Instagram Client (for extracting info only)
cl = Client()
cl.delay_range = [2, 5]

def download_srt_file(srt_url):
    """Downloads SRT subtitle file from URL and returns its content."""
    print(f"Downloading SRT file from: {srt_url}")
    try:
        response = requests.get(srt_url, timeout=30)
        response.raise_for_status()
        
        # Try to decode as UTF-8, fallback to other encodings if needed
        try:
            content = response.text
        except UnicodeDecodeError:
            content = response.content.decode('latin-1')
        
        return content
    except Exception as e:
        print(f"Error downloading SRT file: {e}")
        return None

def parse_srt_content(srt_content):
    """Parses SRT content and extracts all subtitle text."""
    if not srt_content:
        return None
    
    # Remove BOM if present
    srt_content = srt_content.lstrip('\ufeff')
    
    # Pattern to match SRT format: number, timestamp, text
    # Split by double newlines to get individual subtitle blocks
    blocks = re.split(r'\n\s*\n', srt_content.strip())
    
    subtitle_texts = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
        
        # Skip the first line (subtitle number) and second line (timestamp)
        # Get all remaining lines as subtitle text
        text_lines = lines[2:]
        subtitle_text = ' '.join(text_lines).strip()
        
        if subtitle_text:
            subtitle_texts.append(subtitle_text)
    
    # Join all subtitles into one text
    full_text = ' '.join(subtitle_texts)
    return full_text if full_text else None

def generate_caption_from_srt(srt_text):
    """Uses Gemini to generate an Instagram caption from SRT subtitle text."""
    print("Generating caption from SRT content with Gemini...")
    
    prompt = """You are a social media expert. Based on the following English subtitle text from a video, create an engaging Instagram caption in Persian (Farsi). 

The caption should:
- Be creative and engaging
- Summarize or highlight the key message from the subtitles
- Be relevant to the content
- Use appropriate emojis
- Include 5-10 relevant hashtags in Persian or English at the end
- Be suitable for Instagram audience

Subtitle text:
{srt_text}

Output ONLY the caption with hashtags, nothing else."""

    try:
        formatted_prompt = prompt.format(srt_text=srt_text[:2000])  # Limit to 2000 chars to avoid token limits
        gen_resp = model.generate_content(formatted_prompt)
        
        if gen_resp and gen_resp.text:
            caption = gen_resp.text.strip()
            print(f"\nGenerated Caption:\n{caption}\n")
            return caption
        return None
    except Exception as e:
        print(f"Error generating caption: {e}")
        traceback.print_exc()
        return None

def download_video(link):
    """Downloads video from Instagram link or direct URL."""
    print(f"Downloading video from: {link}")
    
    # Check if it's a direct video URL (not Instagram)
    video_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv']
    is_direct_url = any(link.lower().endswith(ext) for ext in video_extensions) or '/video' in link.lower() or '/uploads' in link.lower()
    
    # If it's a direct URL, download directly
    if is_direct_url and not ('instagram.com' in link or 'instagr.am' in link):
        print("Detected direct video URL, downloading directly...")
        try:
            # Extract filename from URL or generate one
            filename = link.split('/')[-1]
            if not filename or '.' not in filename:
                filename = f"video_{int(time.time())}.mp4"
            
            # Remove query parameters if any
            filename = filename.split('?')[0]
            
            local_path = filename
            print(f"Downloading to: {local_path}")
            
            response = requests.get(link, stream=True, timeout=60)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            if total_size > 0:
                print(f"File size: {total_size / (1024*1024):.2f} MB")
            
            with open(local_path, 'wb') as f:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"\rDownloaded: {percent:.1f}%", end='', flush=True)
            
            print(f"\n✅ Direct download successful: {local_path}")
            return local_path
            
        except Exception as e:
            print(f"❌ Direct download failed: {e}")
            traceback.print_exc()
            return None
    
    # Otherwise, treat as Instagram link
    print("Treating as Instagram link...")
    try:
        # Load cookies (optional - may not be needed for some downloads)
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
        
        # Try different methods to get media info
        media_info = None
        try:
            print("Fetching media info (v1)...")
            media_info = cl.media_info(media_pk)
        except Exception as e:
            print(f"Standard media_info (v1) failed: {e}")
            
            # Fallback 1: GQL
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

            # Fallback 3: Direct Private Request
            if not media_info:
                try:
                    print("Trying direct private request to bypass Pydantic models...")
                    info_raw = cl.private_request(f"media/{media_pk}/info/")
                    if 'items' in info_raw and info_raw['items']:
                        item = info_raw['items'][0]
                        class DummyInfo:
                            def __init__(self, item):
                                self.media_type = item.get('media_type')
                                self.product_type = item.get('product_type', '')
                                self.user = type('User', (), {'username': item.get('user', {}).get('username')})
                        
                        media_info = DummyInfo(item)
                        print("Direct request successful (Pydantic bypassed).")
                except Exception as e3:
                    print(f"Direct request fallback failed: {e3}")
            
        if not media_info:
            print("Failed to retrieve media info after all attempts.")
            return None
        
        media_type = media_info.media_type
        
        # Only process videos
        if media_type != 2:
            print(f"Media type is {media_type}, expected video (2). Skipping...")
            return None
        
        # Get username of original poster
        username = media_info.user.username if media_info.user else None
        
        local_path = None
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
                        local_path = f"video_{media_pk}.mp4"
                        print(f"Downloading from direct URL...")
                        response = requests.get(video_url, stream=True)
                        with open(local_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        print(f"Direct video download successful: {local_path}")
                    else:
                        print("Could not find video URL in response")
                        return None
            except Exception as de2:
                print(f"Direct video download also failed: {de2}")
                return None
        
        return str(local_path) if local_path else None

    except Exception as e:
        print(f"Error downloading video: {e}")
        if "comet" in str(e).lower() or "script" in str(e).lower():
            print("CRITICAL: Instagram is blocking the request or requiring login/challenge.")
            print("Try refreshing your cookie-insta.json on the server.")
        return None

def reencode_video(input_path):
    """Re-encodes video to ensure compatibility with Instagram (H.264 + AAC)."""
    import subprocess
    
    input_path = str(input_path)
    output_path = input_path.replace('.mp4', '_reencoded.mp4')
    print(f"Re-encoding video for Instagram compatibility...")
    
    try:
        cmd = [
            'ffmpeg', '-i', input_path,
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            '-y',
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Re-encoding successful!")
            os.remove(input_path)
            os.rename(output_path, input_path)
            return input_path
        else:
            print(f"Re-encoding failed: {result.stderr}")
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
    print(f"📤 Uploading {file_path} to tmpfiles.org...")
    
    # Check file size
    file_size = os.path.getsize(file_path)
    file_size_mb = file_size / (1024 * 1024)
    print(f"   File size: {file_size_mb:.2f} MB")
    
    if file_size_mb > 100:
        print(f"⚠️  Warning: File is large ({file_size_mb:.2f} MB). Upload may take time or fail.")
    
    try:
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'video/mp4')}
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.post('https://tmpfiles.org/api/v1/upload', files=files, headers=headers, timeout=300)
            
            if response.status_code != 200:
                print(f"❌ HTTP Error {response.status_code}: {response.text[:200]}")
                return None
            
            result = response.json()
            
            if result.get('status') == 'success':
                url = result['data']['url']
                # tmpfiles.org returns URL like: https://tmpfiles.org/12345/file.mp4
                # We need the direct download link: https://tmpfiles.org/dl/12345/file.mp4
                direct_url = url.replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"✅ Upload successful!")
                print(f"   Original URL: {url}")
                print(f"   Direct URL: {direct_url}")
                
                # Verify the URL is accessible
                print("🔍 Verifying URL is accessible...")
                try:
                    verify_resp = requests.head(direct_url, timeout=10, allow_redirects=True)
                    if verify_resp.status_code == 200:
                        print(f"✅ URL verified! Status: {verify_resp.status_code}")
                        return direct_url
                    else:
                        print(f"⚠️  URL returned status {verify_resp.status_code}, but continuing anyway...")
                        # Try GET request
                        verify_resp2 = requests.get(direct_url, timeout=10, stream=True)
                        if verify_resp2.status_code == 200:
                            print(f"✅ URL verified with GET! Status: {verify_resp2.status_code}")
                            return direct_url
                        else:
                            print(f"❌ URL verification failed! Status: {verify_resp2.status_code}")
                            print(f"   Response: {verify_resp2.text[:200]}")
                            return None
                except Exception as verify_error:
                    print(f"⚠️  Could not verify URL: {verify_error}")
                    print(f"   Continuing anyway with URL: {direct_url}")
                    return direct_url
            else:
                print(f"❌ Upload failed: {result}")
                if 'error' in result:
                    print(f"   Error details: {result['error']}")
                return None
    except requests.exceptions.Timeout:
        print(f"❌ Upload timeout (file may be too large)")
        return None
    except Exception as e:
        print(f"❌ Error uploading to tmpfiles: {e}")
        traceback.print_exc()
        return None

def publish_to_instagram(video_url, caption):
    """Publishes video using Instagram Graph API."""
    print(f"📤 Publishing video via Graph API...")
    print(f"   Video URL: {video_url[:80]}...")
    print(f"   Caption length: {len(caption)} characters")
    
    # Verify URL is accessible before sending to Instagram
    print("🔍 Final verification: Testing if Instagram can access the video URL...")
    try:
        test_resp = requests.head(video_url, timeout=15, allow_redirects=True)
        if test_resp.status_code not in [200, 206]:  # 206 is partial content, also OK
            print(f"⚠️  Warning: URL returned status {test_resp.status_code}")
            # Try GET request
            test_resp2 = requests.get(video_url, timeout=15, stream=True)
            if test_resp2.status_code not in [200, 206]:
                print(f"❌ URL is not accessible! Status: {test_resp2.status_code}")
                print(f"   This will likely cause Instagram API to fail.")
                print(f"   Response: {test_resp2.text[:200]}")
                return False
            else:
                print(f"✅ URL is accessible (status: {test_resp2.status_code})")
        else:
            print(f"✅ URL is accessible (status: {test_resp.status_code})")
    except Exception as e:
        print(f"⚠️  Could not verify URL accessibility: {e}")
        print(f"   Continuing anyway, but Instagram may not be able to access it...")
    
    base_url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_ACCOUNT_ID}/media"
    
    try:
        # Use REELS (VIDEO type is not supported for this account)
        payload = {
            'access_token': ACCESS_TOKEN,
            'caption': caption,
            'media_type': 'REELS',
            'video_url': video_url
        }
        
        # Step 1: Create Main Container
        print("📦 Step 1: Creating media container (type: REELS)...")
        resp = requests.post(base_url, data=payload, timeout=60)
        
        # Check HTTP status
        if resp.status_code != 200:
            print(f"❌ HTTP Error {resp.status_code}: {resp.text}")
            return False
        
        result = resp.json()
        
        # Check for API errors
        if 'error' in result:
            error_msg = result['error'].get('message', 'Unknown error')
            error_code = result['error'].get('code', 'Unknown')
            error_subcode = result['error'].get('error_subcode', '')
            print(f"❌ API Error ({error_code}, subcode: {error_subcode}): {error_msg}")
            print(f"   Full error: {result['error']}")
            return False
        
        if 'id' not in result:
            print(f"❌ Error: No container ID in response: {result}")
            return False
        
        creation_id = result['id']
        print(f"✅ Container created! ID: {creation_id}")
        
        # Step 2: Wait & Check Status
        print("⏳ Step 2: Waiting for video to be processed...")
        time.sleep(10)
        
        status_url = f"https://graph.facebook.com/v18.0/{creation_id}"
        max_retries = 30
        status_finished = False
        
        for attempt in range(max_retries):
            status_resp = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}, timeout=30)
            
            if status_resp.status_code != 200:
                print(f"⚠️  HTTP Error {status_resp.status_code} checking status: {status_resp.text}")
                time.sleep(10)
                continue
            
            status_data = status_resp.json()
            
            # Check for API errors
            if 'error' in status_data:
                error_msg = status_data['error'].get('message', 'Unknown error')
                print(f"❌ API Error checking status: {error_msg}")
                return False
            
            code = status_data.get('status_code')
            print(f"   Attempt {attempt + 1}/{max_retries}: Status = {code}")
            
            if code == 'FINISHED':
                print("✅ Video processing finished!")
                status_finished = True
                break
            elif code == 'ERROR':
                error_info = status_data.get('error', {})
                error_msg = error_info.get('message', 'Unknown error') if isinstance(error_info, dict) else str(error_info)
                print(f"❌ Error in media processing: {error_msg}")
                print(f"   Full status data: {status_data}")
                return False
            elif code == 'IN_PROGRESS':
                print(f"   Still processing... waiting 10 seconds...")
            else:
                print(f"   Unknown status: {code}, waiting...")
            
            time.sleep(10)
        
        if not status_finished:
            print(f"❌ Timeout: Video processing did not finish after {max_retries} attempts")
            return False

        # Step 3: Publish
        print("🚀 Step 3: Publishing video to Instagram...")
        publish_url = f"https://graph.facebook.com/v18.0/{INSTAGRAM_ACCOUNT_ID}/media_publish"
        pub_resp = requests.post(publish_url, data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}, timeout=60)
        
        # Check HTTP status
        if pub_resp.status_code != 200:
            print(f"❌ HTTP Error {pub_resp.status_code} during publish: {pub_resp.text}")
            return False
        
        pub_result = pub_resp.json()
        
        # Check for API errors
        if 'error' in pub_result:
            error_msg = pub_result['error'].get('message', 'Unknown error')
            error_code = pub_result['error'].get('code', 'Unknown')
            print(f"❌ API Error during publish ({error_code}): {error_msg}")
            print(f"   Full error: {pub_result['error']}")
            return False
        
        if 'id' in pub_result:
            post_id = pub_result['id']
            print(f"✅✅✅ Successfully published! Post ID: {post_id}")
            print(f"   You can view it at: https://www.instagram.com/p/{post_id}/")
            return True
        else:
            print(f"❌ Error: No post ID in publish response: {pub_result}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"❌ Timeout error during API request")
        traceback.print_exc()
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ Unexpected error during publishing: {e}")
        traceback.print_exc()
        return False

def test_url_for_instagram(url):
    """Tests if a URL is accessible and Instagram can use it."""
    print(f"🔍 Testing URL accessibility: {url[:80]}...")
    try:
        # Test with HEAD request first (faster)
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; InstagramBot/1.0)',
            'Range': 'bytes=0-1024'  # Request first 1KB to test accessibility
        }
        resp = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
        
        if resp.status_code in [200, 206, 301, 302, 307, 308]:
            print(f"✅ URL is accessible (HEAD status: {resp.status_code})")
            # Try GET request to make sure it's really accessible
            get_resp = requests.get(url, headers=headers, timeout=15, stream=True)
            if get_resp.status_code in [200, 206]:
                content_type = get_resp.headers.get('Content-Type', '')
                if 'video' in content_type.lower() or 'mp4' in content_type.lower():
                    print(f"✅ URL is valid video URL (Content-Type: {content_type})")
                    return True
                else:
                    print(f"⚠️  URL accessible but Content-Type is: {content_type}")
                    return True  # Still try it
            else:
                print(f"⚠️  GET request returned status: {get_resp.status_code}")
                return False
        else:
            print(f"❌ URL returned status: {resp.status_code}")
            return False
    except requests.exceptions.Timeout:
        print(f"❌ URL test timeout")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ URL test failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error testing URL: {e}")
        return False

def process_single_row(video_link, srt_link):
    """Processes a single row: downloads SRT, generates caption, downloads video, and posts."""
    print(f"\n--- Processing Video: {video_link} ---")
    print(f"--- SRT Link: {srt_link} ---")
    
    # Step 1: Download and parse SRT
    srt_content = download_srt_file(srt_link)
    if not srt_content:
        print("Failed to download SRT file.")
        return False
    
    srt_text = parse_srt_content(srt_content)
    if not srt_text:
        print("Failed to parse SRT content.")
        return False
    
    print(f"SRT text extracted ({len(srt_text)} characters)")
    
    # Step 2: Generate caption from SRT
    caption = generate_caption_from_srt(srt_text)
    if not caption:
        print("Failed to generate caption.")
        return False
    
    # Step 3: Test if original video URL is accessible for Instagram
    print("\n📋 Step 3: Testing original video URL...")
    use_original_url = test_url_for_instagram(video_link)
    
    public_url = None
    video_path = None
    processed_video = None
    
    if use_original_url:
        print("✅ Original URL is accessible! Using it directly (no need to upload to tmpfiles).")
        public_url = video_link
    else:
        print("⚠️  Original URL is not accessible. Downloading and uploading to tmpfiles...")
        
        # Step 4: Download video
        video_path = download_video(video_link)
        if not video_path:
            print("Failed to download video.")
            return False
        
        print(f"Video downloaded to: {video_path}")
        
        try:
            # Step 5: Re-encode video if needed
            processed_video = reencode_video(video_path)
            
            # Step 6: Upload video to tmpfiles
            public_url = upload_to_tmpfiles(processed_video)
            if not public_url:
                print("❌ Failed to upload video to tmpfiles.org")
                print("   The video file is still available locally if you want to try manual upload.")
                return False
            
            # Double-check URL format
            if not public_url.startswith('http'):
                print(f"❌ Invalid URL format: {public_url}")
                return False
        
        except Exception as e:
            print(f"Error processing video: {e}")
            traceback.print_exc()
            return False
    
    print(f"✅ Video URL ready: {public_url}")
    
    # Step 7: Publish to Instagram
    success = publish_to_instagram(public_url, caption)
    
    # Cleanup (only if we downloaded the video)
    if processed_video and os.path.exists(processed_video):
        try:
            os.remove(processed_video)
            print(f"Cleaned up {processed_video}")
        except:
            pass
    
    if video_path and os.path.exists(video_path) and video_path != processed_video:
        try:
            os.remove(video_path)
            print(f"Cleaned up {video_path}")
        except:
            pass
    
    return success

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
        print("1. Go to Google Cloud Console.")
        print("2. Create a service account and download the JSON key.")
        print("3. Rename it to 'credentials.json' and place it in this folder.")
        print("4. Share your Google Sheet with the email in the JSON file.")
        return None

def main():
    print("Starting Video Bot with Google Sheets integration...")
    print("This bot processes videos with SRT subtitles from Sheet 'Video-2'")
    
    sheet_id = "1i6_qINdzyMF5FJcigKiLdtxcVv_DBWUAlMM4xc-QzCY"
    worksheet_name = "YaShans"
    
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

            # Open the worksheet (try specified name, fallback to first worksheet)
            try:
                worksheet = sheet_obj.worksheet(worksheet_name)
                print(f"✅ Using worksheet: '{worksheet_name}'")
            except gspread.exceptions.WorksheetNotFound:
                print(f"⚠️  Worksheet '{worksheet_name}' not found in spreadsheet!")
                # List all available worksheets
                all_worksheets = sheet_obj.worksheets()
                print(f"Available worksheets: {[ws.title for ws in all_worksheets]}")
                
                # Try to use the first worksheet as fallback
                if all_worksheets:
                    worksheet = all_worksheets[0]
                    print(f"✅ Using first available worksheet: '{worksheet.title}'")
                else:
                    print("❌ No worksheets found in spreadsheet!")
                    time.sleep(60)
                    continue
            
            # Get all records (including header)
            rows = worksheet.get_all_values()
            
            found_job = False
            for i, row in enumerate(rows):
                if i == 0: continue  # Skip header
                
                # Columns: A (0) = video link, B (1) = SRT link (if E is empty), E (4) = SRT link (if filled), F (5) = status
                if len(row) < 2:
                    print(f"⚠️  Row {i+1}: Skipped (less than 2 columns)")
                    continue
                
                video_link = row[0].strip() if len(row) > 0 else ""
                srt_link_e = row[4].strip() if len(row) > 4 else ""  # Column E (index 4) = SRT link
                srt_link_b = row[1].strip() if len(row) > 1 else ""  # Column B (index 1) = SRT link (fallback)
                status = row[5].strip() if len(row) > 5 else ""  # Column F (index 5) = status
                
                # If column E is empty, use column B for SRT link
                if not srt_link_e:
                    srt_link = srt_link_b
                    srt_source = "B"
                else:
                    srt_link = srt_link_e
                    srt_source = "E"
                
                # Skip if already processed successfully
                if status and status.lower() == "yes":
                    print(f"✅ Row {i+1}: Already processed (status: {status})")
                    continue
                
                # Skip if video link is missing
                if not video_link:
                    print(f"⚠️  Row {i+1}: Skipped (video link in column A is empty)")
                    continue
                
                # Skip if SRT link is missing (both E and B are empty)
                if not srt_link:
                    print(f"⚠️  Row {i+1}: Skipped (SRT link is empty in both column B and E)")
                    print(f"   Video link: {video_link[:50]}...")
                    continue
                
                print(f"\n--- Processing row {i+1} ---")
                print(f"   Video link (A): {video_link[:60]}...")
                print(f"   SRT link ({srt_source}): {srt_link[:60]}...")
                found_job = True
                success = process_single_row(video_link, srt_link)
                
                if success:
                    print(f"Process successful! Updating row {i+1}...")
                    worksheet.update_cell(i + 1, 6, "Yes")  # Column 6 (F) for status
                else:
                    print(f"Process failed for row {i+1}. Marking as 'No'...")
                    worksheet.update_cell(i + 1, 6, "No")  # Mark as failed
                    
                    # Wait between posts to avoid rate limits
                    wait_seconds = POST_INTERVAL_MINUTES * 60
                    print(f"Waiting {POST_INTERVAL_MINUTES} minute(s) before checking next row...")
                    time.sleep(wait_seconds)
            
            if not found_job:
                print(f"No new links to process. Checking again in {POST_INTERVAL_MINUTES * 5} minutes...")
                time.sleep(POST_INTERVAL_MINUTES * 5 * 60)
                
        except Exception as e:
            print(f"Error in main loop: {e}")
            traceback.print_exc()
            time.sleep(60)

if __name__ == "__main__":
    main()

