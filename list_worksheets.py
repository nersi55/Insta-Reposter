#!/usr/bin/env python3
"""
Helper script to list all worksheets in the Google Sheet.
This helps you find the correct worksheet name.
"""

import os
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

def list_worksheets():
    """Lists all worksheets in the Google Sheet."""
    sheet_id = "1i6_qINdzyMF5FJcigKiLdtxcVv_DBWUAlMM4xc-QzCY"
    
    if not os.path.exists("credentials.json"):
        print("❌ credentials.json not found!")
        print("Please add your Google Service Account credentials.json file.")
        return
    
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        client = gspread.authorize(creds)
        
        sheet_obj = client.open_by_key(sheet_id)
        worksheets = sheet_obj.worksheets()
        
        print(f"\n📊 Spreadsheet: {sheet_obj.title}")
        print(f"📋 Found {len(worksheets)} worksheet(s):\n")
        
        for i, ws in enumerate(worksheets, 1):
            row_count = len(ws.get_all_values())
            print(f"  {i}. '{ws.title}' ({row_count} rows)")
        
        print(f"\n💡 To use a specific worksheet, update 'worksheet_name' in Video_bot.py")
        print(f"   Current setting: worksheet_name = 'YaShans'")
        
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"❌ Spreadsheet with ID '{sheet_id}' not found!")
    except (gspread.exceptions.APIError, PermissionError) as e:
        print(f"❌ Permission Denied (403).")
        print("CRITICAL: You MUST share the spreadsheet with this email:")
        print("web-client-1@plenary-net-476220-c9.iam.gserviceaccount.com")
        print("Set the role to 'Editor'.")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    list_worksheets()

