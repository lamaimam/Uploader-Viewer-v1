# uplink/dsa_client.py
import os
from typing import Dict, Optional, Any, Tuple

from girder_client import GirderClient
from django.conf import settings


def _config() -> Dict[str, str]:
    """
    Centralized DSA configuration from Django settings.
    """
    api = (getattr(settings, "DSA_API_URL", "") or "").rstrip("/")
    web = (getattr(settings, "DSA_WEB_BASE", "") or "").rstrip("/")
    coll = getattr(settings, "DSA_COLLECTION_ID", None)
    key = getattr(settings, "DSA_SERVICE_API_KEY", None)
    return {
        "api": api,
        "web": web,
        "coll": coll,
        "key": key,
    }


class DSAClient:
    """
    Minimal DSA helper focused on:

    - Auth via API key
    - Deriving a *case name* from the filename (ID prefix)
    - Finding/creating a case folder under the configured collection
    - Ensuring a "Slides" subfolder exists
    - Uploading **real, non-zero files** using Girder's uploadFileToItem
    """

    def __init__(self, user_token: Optional[str] = None):
        self.cfg = _config()

        api = self.cfg["api"]
        if api.endswith("/api/v1"):
            api_url = api
        else:
            api_url = api + "/api/v1"

        self.gc = GirderClient(apiUrl=api_url)
        token = user_token or self.cfg["key"]
        self.gc.authenticate(apiKey=token)

    # ------------------------------------------------------------------
    # Case naming / grouping
    # ------------------------------------------------------------------
    @staticmethod
    def extract_case_name(filename: str) -> str:
        """
        Extract a case name from filename using your original rule:

        - Take base name (without path or extension)
        - Split on first '-' and use left side as the case ID

        e.g. "4439-RQ-24-24-1-S23-22919-H&E-TIFF.tiff" -> "4439"
        """
        base = os.path.splitext(os.path.basename(filename))[0]
        parts = base.split("-", 1)
        case_name = parts[0].strip() if parts else base.strip()
        if not case_name:
            case_name = "Untitled"
        return case_name

    # ------------------------------------------------------------------
    # Case / Slides helpers
    # ------------------------------------------------------------------
    def find_case(self, case_name: str) -> Optional[Dict[str, Any]]:
        """
        Find an existing case folder with the given name under the collection,
        and ensure it has a "Slides" subfolder.
        """
        coll = self.cfg["coll"]
        folders = self.gc.get("folder", parameters={
            "parentType": "collection",
            "parentId": coll,
            "limit": 0,
        })

        for f in folders:
            if f.get("name") == case_name:
                # Ensure "Slides" subfolder exists
                subs = self.gc.get("folder", parameters={
                    "parentType": "folder",
                    "parentId": f["_id"],
                    "limit": 0,
                })
                slides = None
                for s in subs:
                    if s.get("name") == "Slides":
                        slides = s
                        break
                if not slides:
                    slides = self.gc.post("folder", data={
                        "parentType": "folder",
                        "parentId": f["_id"],
                        "name": "Slides",
                    })
                f["subfolders"] = {"Slides": slides}
                return f

        return None

    def create_case(self, case_name: str) -> Dict[str, Any]:
        """
        Create a new case folder with a 'Slides' subfolder.
        """
        case = self.gc.post("folder", data={
            "parentType": "collection",
            "parentId": self.cfg["coll"],
            "name": case_name,
        })
        slides = self.gc.post("folder", data={
            "parentType": "folder",
            "parentId": case["_id"],
            "name": "Slides",
        })
        case["subfolders"] = {"Slides": slides}
        return case

    def ensure_case_for_filename(self, filename: str) -> Dict[str, Any]:
        """
        Given a filename, determine its case name and return a case folder
        (create if needed), always with a 'Slides' subfolder.
        """
        case_name = self.extract_case_name(filename)
        print(f"DEBUG → ensure_case_for_filename: filename={filename}, case_name={case_name}")
        case = self.find_case(case_name)
        if case is None:
            print("DEBUG → Case not found; creating new case:", case_name)
            case = self.create_case(case_name)
        else:
            print("DEBUG → Reusing existing case:", case_name, "id:", case["_id"])
        return case

    # ------------------------------------------------------------------
    # Upload – Girder only, no external S3
    # ------------------------------------------------------------------
    def upload_file_to_slides(self, slides_folder_id: str, path: str, filename: str) -> str:
        """
        Upload a REAL file (must exist and be non-zero size) into the 'Slides'
        folder using Girder's chunked upload (uploadFileToItem).

        Returns:
            item_id (str): The created item ID in DSA.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"File does not exist on disk: {path}")

        size = os.path.getsize(path)
        print(f"DEBUG → upload_file_to_slides: {filename} ({size} bytes)")

        if size == 0:
            raise ValueError(f"Refusing to upload zero-byte file: {filename}")

        # 1️⃣ Create item under Slides folder
        item = self.gc.post("item", data={
            "folderId": slides_folder_id,
            "name": filename,
        })
        item_id = item["_id"]
        print("DEBUG → Created item:", item_id)

        # 2️⃣ Upload file contents via Girder
        self.gc.uploadFileToItem(item_id, path)
        print("DEBUG → Girder upload complete for file:", filename)

        return item_id

    # ------------------------------------------------------------------
    # High-level helper: upload one file and group into a case
    # ------------------------------------------------------------------
    def upload_case_file(self, path: str, filename: str) -> Tuple[str, str]:
        """
        - Derive case name from filename (ID prefix)
        - Find/create that case and its 'Slides' folder
        - Upload the file into 'Slides'
        - Return (case_name, item_id)
        """
        case = self.ensure_case_for_filename(filename)
        slides_folder_id = case["subfolders"]["Slides"]["_id"]
        item_id = self.upload_file_to_slides(slides_folder_id, path, filename)
        return case["name"], item_id
