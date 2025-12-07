# uplink/dsa_client.py
import os
from typing import Dict, Optional, Any, Tuple, List

from girder_client import GirderClient
from django.conf import settings


def _config() -> Dict[str, str]:
    api = (getattr(settings, "DSA_API_URL", "") or "").rstrip("/")
    coll = getattr(settings, "DSA_COLLECTION_ID", None)
    key = getattr(settings, "DSA_SERVICE_API_KEY", None)
    return {
        "api": api,
        "coll": coll,
        "key": key,
    }


class DSAClient:
    """
    DSA helper with *no* gc.post("file") and *no* presigned S3.

    - Only uses GirderClient.uploadFileToItem (stream + complete)
    - After upload, verifies file size in DSA
    - If size is zero or file missing, deletes the item → no placeholders
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
    # Case naming / grouping: RQ-23-1-SP23-960 style
    # ------------------------------------------------------------------
    @staticmethod
    def extract_case_name(filename: str) -> str:
        """
        Derive the case name starting at 'RQ' and stopping before stain/format markers.

        Example:
          1999-RQ-23-1-SP23-960-PDL1-TIFF.tiff
            -> "RQ-23-1-SP23-960"
        """
        base = os.path.splitext(os.path.basename(filename))[0]
        tokens = [t for t in base.split("-") if t]

        if not tokens:
            return "Untitled-Case"

        MARKERS = {
            "H&E", "HE",
            "PDL1", "PD-L1",
            "TIFF", "NDPI", "SVS",
            "JPEG", "JPG", "PNG"
        }

        # Find first token starting with RQ
        start_idx = None
        for i, tok in enumerate(tokens):
            if tok.upper().startswith("RQ"):
                start_idx = i
                break

        if start_idx is None:
            usable: List[str] = []
            for tok in tokens:
                if tok.upper() in MARKERS:
                    break
                usable.append(tok)
            case_name = "-".join(usable).strip("-_ ")
            return case_name or "Untitled-Case"

        case_tokens: List[str] = []
        for tok in tokens[start_idx:]:
            if tok.upper() in MARKERS:
                break
            case_tokens.append(tok)

        case_name = "-".join(case_tokens).strip("-_ ")
        return case_name or "Untitled-Case"

    # ------------------------------------------------------------------
    # Case / Slides helpers
    # ------------------------------------------------------------------
    def find_case(self, case_name: str) -> Optional[Dict[str, Any]]:
        coll = self.cfg["coll"]
        folders = self.gc.get("folder", parameters={
            "parentType": "collection",
            "parentId": coll,
            "limit": 0,
        })

        for f in folders:
            if f.get("name") == case_name:
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
    # Upload – Girder only, with post-upload verification
    # ------------------------------------------------------------------
    def upload_file_to_slides(self, slides_folder_id: str, path: str, filename: str) -> str:
        """
        Upload file into Slides using GirderClient.uploadFileToItem().
        S3 will use the ITEM NAME (filename), so the internal file object
        name does not matter.
        """

        if not os.path.exists(path):
            raise FileNotFoundError(f"File does not exist: {path}")

        size = os.path.getsize(path)
        print(f"DEBUG → upload_file_to_slides: {filename} ({size} bytes)")

        # Remove any previous item with same name
        existing = self.find_item_in_slides(slides_folder_id, filename)
        if existing:
            old_id = existing["_id"]
            print("DEBUG → Removing old item:", old_id)
            self.delete_item(old_id)

        # Create new item with correct ITEM NAME
        item = self.gc.post("item", data={
            "folderId": slides_folder_id,
            "name": filename,
        })
        item_id = item["_id"]
        print("DEBUG → Created new item:", item_id)

        try:
            # Simple, stable Girder upload
            self.gc.uploadFileToItem(item_id, path)
            print("DEBUG → Girder upload complete for:", filename)

            # Verify the file attached
            files = self.gc.get(f"item/{item_id}/files")
            if not files:
                raise RuntimeError("DSA item has zero files after upload")

            return item_id

        except Exception as e:
            print("ERROR → Upload failed, deleting item:", item_id, "error:", e)
            try:
                self.gc.delete(f"item/{item_id}")
            except:
                pass
            raise

    # ------------------------------------------------------------------
    # High-level helper: upload one file and group into a case
    # ------------------------------------------------------------------
    def upload_case_file(self, path: str, filename: str) -> Tuple[str, str]:
        case = self.ensure_case_for_filename(filename)
        slides_folder_id = case["subfolders"]["Slides"]["_id"]

        # -----------------------------------------
        # OVERWRITE: remove existing item if exists
        # -----------------------------------------
        existing = self.find_item_in_slides(slides_folder_id, filename)
        if existing:
            print(f"DEBUG → Removing existing DSA item before upload: {existing['_id']} ({filename})")
            self.delete_item(existing["_id"])

        # Proceed with upload
        item_id = self.upload_file_to_slides(slides_folder_id, path, filename)

        return case["name"], item_id

    # ------------------------------------------------------------------
    # NEW: Find an item in the Slides folder by exact filename
    # ------------------------------------------------------------------
    def find_item_in_slides(self, slides_folder_id: str, filename: str):
        items = self.gc.get("item", parameters={
            "folderId": slides_folder_id,
            "name": filename,
            "limit": 0,
        })
        if items:
            return items[0]
        return None

    def find_case_for_filename(self, filename: str):
        """
        Given a filename, find the case folder in DSA that contains an item with that name.
        """
        coll = self.cfg["coll"]
        folders = self.gc.get("folder", parameters={
            "parentType": "collection",
            "parentId": coll,
            "limit": 0,
        })

        for f in folders:
            case_id = f["_id"]

            items = self.gc.get("item", parameters={
                "folderId": case_id,
                "limit": 0
            })

            for it in items:
                if it["name"] == filename:
                    # FOUND the case containing this file
                    f["subfolders"] = {}
                    return f

        return None

    # ------------------------------------------------------------------
    # NEW: Delete a DSA item by ID
    # ------------------------------------------------------------------
    def delete_item(self, item_id: str):
        try:
            self.gc.delete(f"item/{item_id}")
            return True
        except Exception as e:
            print(f"ERROR → Failed to delete item {item_id}: {e}")
            return False

    def download_file_bytes(self, file_id: str) -> bytes:
        """
        Download the raw binary from DSA using the file/<id>/download endpoint.
        This is the correct API for Girder/S3-backed or local assetstores.
        """
        try:
            # jsonResp=False → return raw bytes, not JSON
            resp = self.gc.get(f"file/{file_id}/download", jsonResp=False)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            print("ERROR → download_file_bytes failed:", e)
            raise RuntimeError(f"Failed to download file {file_id} from DSA") from e

