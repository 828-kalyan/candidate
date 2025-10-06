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
import os
import json
import zipfile
import logging
from flask import Flask, request, render_template, send_file, abort, url_for

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# =====================
# Google Drive Settings
# =====================
SERVICE_ACCOUNT_FILE = "service_account.json"   # Default local path; can be overridden by env
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
PARENT_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_PARENT_FOLDER_ID", "18-aW4c8Mu4S7UQVGOldrZFPkeHhlI_h3")


# ---------------------
# Helpers for Google Drive
# ---------------------
def build_drive_service():
    """Builds a Google Drive API service if credentials are available.

    Credentials can be provided via either:
      - GOOGLE_SERVICE_ACCOUNT_JSON (env var with full JSON), or
      - SERVICE_ACCOUNT_FILE (env var path) / fallback to SERVICE_ACCOUNT_FILE constant.

    Returns None if Google libraries are unavailable or credentials are missing/invalid.
    """
    try:
        # Lazy import to avoid hard failure at startup if libs absent
        from google.oauth2 import service_account as g_service_account
        from googleapiclient.discovery import build as g_build
        from googleapiclient.http import MediaIoBaseDownload  # noqa: F401  # used elsewhere
    except Exception as import_err:
        logging.warning("Google API client unavailable: %s", import_err)
        return None

    creds = None
    sa_json_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json_env:
        try:
            info = json.loads(sa_json_env)
            creds = g_service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            logging.error("Invalid GOOGLE_SERVICE_ACCOUNT_JSON: %s", e)
            return None
    else:
        sa_path = os.environ.get("SERVICE_ACCOUNT_FILE", SERVICE_ACCOUNT_FILE)
        if not os.path.exists(sa_path):
            logging.warning("Service account file not found at %s", sa_path)
            return None
        creds = g_service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)

    try:
        return g_build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logging.error("Failed to build Google Drive service: %s", e)
        return None


def get_tool_binary_path():
    """Return path to monitoring tool binary, if present."""
    candidates = [
        os.path.join("static", "monitoring_tool.exe"),
        os.path.join(os.getcwd(), "tool.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

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
    # Local import to avoid module-level dependency when Drive is unused
    from googleapiclient.http import MediaIoBaseDownload
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

    # Build drive service (optional; app should still work without it)
    drive_service = build_drive_service()
    server_url = ""
    session_id = ""
    if drive_service:
        # Folder naming: YYYY-MM-DD
        date_part = interview_time.split("_")[0]
        folder_id = get_folder_id(drive_service, date_part, PARENT_FOLDER_ID)
        if not folder_id:
            logging.warning("Date folder not found in Drive for %s", date_part)
        else:
            # Filename convention (adjust if your Drive names differ)
            filename = f"{email}_{interview_time}.txt"
            file_id = find_file_id(drive_service, filename, folder_id)
            if not file_id:
                logging.warning("Config file not found in Drive: %s", filename)
            else:
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
        tool_path = get_tool_binary_path()
        if tool_path:
            zf.write(tool_path, arcname="monitoring_tool.exe")
        else:
            logging.warning("Monitoring tool binary not found; delivering config-only zip")
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
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, host="0.0.0.0", port=port)
