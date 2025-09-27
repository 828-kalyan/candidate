# from flask import Flask, request, render_template

# app = Flask(__name__)

# DROPBOX_EXE_URL = "https://drive.google.com/file/d/15FZUPc12eopGoXOGxHsj2cYOx8Nn7bzE/view?usp=drive_link"

# @app.route("/")
# def candidate_page():
#     email = request.args.get("email")
#     interview_time = request.args.get("time")  # e.g. 2025-09-25_12-00
#     return render_template(
#         "candidate.html",
#         email=email,
#         interview_time=interview_time,
#         exe_link=DROPBOX_EXE_URL
#     )

# if __name__ == "__main__":
#     app.run(debug=True)


import io
import zipfile
import logging
import os
import json
from flask import Flask, request, render_template, send_file, abort, url_for
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================
# Google Drive Settings
# =====================
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
PARENT_FOLDER_ID = "18-aW4c8Mu4S7UQVGOldrZFPkeHhlI_h3"  # Adjust to your Drive folder ID

# ---------------------
# Helpers for Google Drive
# ---------------------
def build_drive_service():
    try:
        # Get service account JSON from environment variable
        service_account_json = os.environ.get("SERVICE_ACCOUNT_JSON")
        if not service_account_json:
            logging.error("Environment variable SERVICE_ACCOUNT_JSON not found.")
            return None

        # Parse JSON string into credentials
        creds_dict = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=SCOPES
        )
        drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
        logging.info("Successfully authenticated with Google Drive using environment variable.")
        return drive_service
    except Exception as e:
        logging.error(f"Failed to authenticate with Google Drive: {e}")
        return None

def get_folder_id(drive_service, folder_name, parent_id):
    if not drive_service:
        logging.error("Drive service unavailable, cannot search for folder.")
        return None
    logging.info(f"Searching for folder: {folder_name} under parent ID: {parent_id}")
    q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    res = drive_service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        folder_id = files[0]["id"]
        logging.info(f"Found folder ID: {folder_id} for {folder_name}")
        return folder_id
    logging.warning(f"Folder {folder_name} not found under parent {parent_id}")
    return None

def find_file_id(drive_service, filename, folder_id):
    if not drive_service:
        logging.error("Drive service unavailable, cannot search for file.")
        return None
    logging.info(f"Searching for file: {filename} in folder ID: {folder_id}")
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    res = drive_service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        file_id = files[0]["id"]
        logging.info(f"Found file ID: {file_id} for {filename}")
        return file_id
    logging.warning(f"File {filename} not found in folder {folder_id}")
    return None

def download_drive_file_content(drive_service, file_id):
    if not drive_service:
        logging.error("Drive service unavailable, cannot download file.")
        return None
    logging.info(f"Attempting to download content from file ID: {file_id}")
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        try:
            _, done = downloader.next_chunk()
        except Exception as e:
            logging.error(f"Download chunk failed for file ID {file_id}: {e}")
            return None
    fh.seek(0)
    content = fh.read().decode("utf-8")
    logging.info(f"Downloaded content: {content}")
    return content

# ---------------------
# Candidate Page
# ---------------------
@app.route("/")
def candidate_page():
    email = request.args.get("email", "")
    interview_time = request.args.get("time", "")
    exe_link = url_for("download_bundle", _external=True, email=email, time=interview_time)
    logging.info(f"Rendering candidate page with raw email={request.args.get('email')}, raw time={request.args.get('time')}, exe_link={exe_link}")
    return render_template("candidate.html", email=email, interview_time=interview_time, exe_link=exe_link)

# ---------------------
# Download Bundle (EXE + Config)
# ---------------------
@app.route("/download-bundle")
def download_bundle():
    # Capture raw params for debugging
    raw_email = request.args.get("email", "")
    raw_time = request.args.get("time", "")
    logging.info(f"Received request with raw email={raw_email}, raw time={raw_time}")

    email = raw_email
    interview_time = raw_time
    logging.info(f"After assignment: email={email}, interview_time={interview_time}")

    if not email or not interview_time:
        logging.error(f"Missing parameters after check: email={email}, interview_time={interview_time}")
        abort(400, "Missing parameters")

    logging.info(f"Starting download bundle for email={email}, time={interview_time}")

    # Build drive service
    drive_service = build_drive_service()
    if not drive_service:
        logging.error("Aborting due to drive service failure")
        abort(500, "Drive service unavailable")

    # Folder naming: YYYY-MM-DD
    date_part = interview_time.split("_")[0]
    logging.info(f"Extracted date part for folder: {date_part}")
    folder_id = get_folder_id(drive_service, date_part, PARENT_FOLDER_ID)
    if not folder_id:
        logging.error(f"Aborting due to missing folder {date_part}")
        abort(404, "Date folder not found")

    # Filename convention
    filename = f"{email}_{interview_time}.txt"
    logging.info(f"Searching for file: {filename}")
    file_id = find_file_id(drive_service, filename, folder_id)
    if not file_id:
        logging.error(f"Aborting due to missing file {filename}")
        abort(404, "Config file not found in Drive")

    # Download content
    content = download_drive_file_content(drive_service, file_id)
    if not content:
        logging.error(f"Aborting due to failed content download for file {file_id}")
        abort(500, "Failed to download config")

    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    server_url = lines[0] if len(lines) > 0 else ""
    session_id = lines[1] if len(lines) > 1 else ""
    logging.info(f"Extracted server_url={server_url}, session_id={session_id} from content")

    # Build config.txt
    config_content = f"""email={email}
interview_time={interview_time}
server_url={server_url}
session_id={session_id}
"""
    logging.info(f"Built config content: {config_content}")

    # Build in-memory ZIP
    memory_file = io.BytesIO()
    try:
        with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
            logging.info("Adding monitoring_tool.exe to zip")
            zf.writestr("monitoring_tool.exe", open("static/monitoring_tool.exe", "rb").read())
            logging.info("Adding config.txt to zip")
            zf.writestr("config.txt", config_content)
        memory_file.seek(0)
        logging.info("Zip file created successfully")
    except Exception as e:
        logging.error(f"Failed to create zip file: {e}")
        abort(500, "Failed to create bundle")

    download_name = f"interview_{email.replace('@','_at_')}_{interview_time}.zip"
    logging.info(f"Sending zip file as attachment: {download_name}")
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/zip"
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
