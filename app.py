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
from flask import Flask, request, render_template, send_file, abort, url_for
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =====================
# Google Drive Settings
# =====================
SERVICE_ACCOUNT_FILE = "service_account.json"   # Keep this only on server!
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
PARENT_FOLDER_ID = "18-aW4c8Mu4S7UQVGOldrZFPkeHhlI_h3"   # Adjust to your Drive folder ID


# ---------------------
# Helpers for Google Drive
# ---------------------
def build_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def get_folder_id(drive_service, folder_name, parent_id):
    q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false"
    res = drive_service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None

def find_file_id(drive_service, filename, folder_id):
    q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    res = drive_service.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None

def download_drive_file_content(drive_service, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read().decode("utf-8")


# ---------------------
# Candidate Page
# ---------------------
@app.route("/")
def candidate_page():
    email = request.args.get("email", "")
    interview_time = request.args.get("time", "")
    exe_link = url_for("download_bundle", _external=True, email=email, time=interview_time)
    return render_template("candidate.html", email=email, interview_time=interview_time, exe_link=exe_link)


# ---------------------
# Download Bundle (EXE + Config)
# ---------------------
@app.route("/download-bundle")
def download_bundle():
    email = request.args.get("email", "")
    interview_time = request.args.get("time", "")
    if not email or not interview_time:
        abort(400, "Missing parameters")

    # Build drive service
    drive_service = build_drive_service()

    # Folder naming: YYYY-MM-DD
    date_part = interview_time.split("_")[0]
    folder_id = get_folder_id(drive_service, date_part, PARENT_FOLDER_ID)
    if not folder_id:
        abort(404, "Date folder not found")

    # Filename convention (adjust if your Drive names differ)
    filename = f"{email}_{interview_time}.txt"
    file_id = find_file_id(drive_service, filename, folder_id)
    if not file_id:
        abort(404, "Config file not found in Drive")

    # Download content from Drive (e.g. "https://server.com/ws\nSESSION_ID_123")
    content = download_drive_file_content(drive_service, file_id)
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    server_url = lines[0] if len(lines) > 0 else ""
    session_id = lines[1] if len(lines) > 1 else ""

    # Build config.txt
    config_content = f"""email={email}
interview_time={interview_time}
server_url={server_url}
session_id={session_id}
"""

    # Build in-memory ZIP
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write("static/monitoring_tool.exe", arcname="monitoring_tool.exe")
        zf.writestr("config.txt", config_content)
    memory_file.seek(0)

    download_name = f"interview_{email.replace('@','_at_')}_{interview_time}.zip"
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/zip"
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
