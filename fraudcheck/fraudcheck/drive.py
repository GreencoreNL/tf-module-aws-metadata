"""Google Drive en Sheets toegang voor de productie run.

Authenticatie via een service account die als 'Inhoudsbeheerder' lid is van de gedeelde drive met de claims
mappen. Zet het pad naar de sleutel in GOOGLE_APPLICATION_CREDENTIALS.
"""
from __future__ import annotations

import io
import os
from typing import Optional

SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets.readonly"]
FOLDER = "application/vnd.google-apps.folder"
GDOC = "application/vnd.google-apps.document"


class Drive:
    def __init__(self, credentials_file: Optional[str] = None):
        from google.oauth2 import service_account  # lazy, alleen nodig in productie
        from googleapiclient.discovery import build

        path = credentials_file or os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        creds = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
        subject = os.environ.get("FRAUDCHECK_IMPERSONATE")  # optioneel, bij domain wide delegation
        if subject:
            creds = creds.with_subject(subject)
        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def list_children(self, folder_id: str, folders_only: bool = False) -> list[dict]:
        q = f"'{folder_id}' in parents and trashed = false"
        if folders_only:
            q += f" and mimeType = '{FOLDER}'"
        out, token = [], None
        while True:
            res = self.svc.files().list(
                q=q, fields="nextPageToken, files(id,name,mimeType,createdTime,modifiedTime)",
                supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=200, pageToken=token,
            ).execute()
            out += res.get("files", [])
            token = res.get("nextPageToken")
            if not token:
                return out

    def download(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        buf = io.BytesIO()
        req = self.svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        return buf.getvalue()

    def ocr_text(self, file_id: str, tmp_parent: str) -> str:
        """Laat Google de pdf of afbeelding OCR'en door hem als Google Doc te kopiëren. De kopie wordt direct verwijderd."""
        copy = self.svc.files().copy(
            fileId=file_id, body={"mimeType": GDOC, "name": "_ocr_tmp", "parents": [tmp_parent]},
            supportsAllDrives=True, fields="id",
        ).execute()
        try:
            data = self.svc.files().export(fileId=copy["id"], mimeType="text/plain").execute()
            return data.decode("utf-8", errors="replace")
        finally:
            self.svc.files().delete(fileId=copy["id"], supportsAllDrives=True).execute()

    def upload_html_as_doc(self, parent_id: str, name: str, html: str) -> dict:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(html.encode("utf-8")), mimetype="text/html", resumable=False)
        return self.svc.files().create(
            body={"name": name, "parents": [parent_id], "mimeType": GDOC},
            media_body=media, supportsAllDrives=True, fields="id,webViewLink",
        ).execute()

    def sheet_rows(self, spreadsheet_id: str, rng: str) -> list[dict]:
        res = self.sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute()
        vals = res.get("values", [])
        if not vals:
            return []
        hdr = [h.strip() for h in vals[0]]
        return [dict(zip(hdr, r + [""] * (len(hdr) - len(r)))) for r in vals[1:]]
