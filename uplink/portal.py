# uplink/portal.py
import os
import tempfile
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv
load_dotenv()
from django.conf import settings
import boto3
import json

from .dsa_client import DSAClient


# =========================================================
#  DSA UPLOAD: Browser → Django → DSA Slides folder
# =========================================================
@csrf_exempt
def upload_case_files_dsa(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "error": "POST required"}, status=405)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"status": "error", "error": "no file"}, status=400)

    filename = f.name
    print("DEBUG → Django received:", filename, "size:", f.size)

    # Write tempfile
    suffix = os.path.splitext(filename)[1] or ".tmp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in f.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        dsa = DSAClient()

        # Determine case and Slides folder
        case = dsa.ensure_case_for_filename(filename)
        slides_folder_id = case["subfolders"]["Slides"]["_id"]

        print("DEBUG → Using case:", case["name"], "| Slides folder:", slides_folder_id)

        # Upload to DSA
        item_id = dsa.upload_file_to_slides(slides_folder_id, tmp_path, filename)

        return JsonResponse({
            "status": "ok",
            "case": case["name"],
            "item_id": item_id
        })

    except Exception as e:
        print("ERROR in upload_case_files_dsa:", e)
        return JsonResponse({"status": "error", "error": str(e)}, status=500)

    finally:
        try:
            os.remove(tmp_path)
        except:
            pass



# =========================================================
#  S3 EXPORT: DSA → Django → S3
# =========================================================
@csrf_exempt
def upload_case_to_s3(request):
    """
    Export slides from DSA (Case → Slides → Items) to S3.

    * Uses the DSA **Item Name** as the final S3 filename.
    * Avoids Girder tmpXXXXX.tiff issues by never reading file_obj["name"].
    """

    print("DEBUG → /api/upload_case_to_s3/ HIT")

    if request.method != "POST":
        return JsonResponse({"status": "error", "error": "POST required"}, status=405)

    # Parse JSON body
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        items = payload.get("items", [])
    except:
        return JsonResponse({"status": "error", "error": "Invalid JSON"}, status=400)

    if not items:
        return JsonResponse({"status": "error", "error": "No items provided"}, status=400)

    # Init DSA + S3
    dsa = DSAClient()

    bucket = os.getenv("S3_BUCKET_NAME")
    if not bucket:
        return JsonResponse({"status": "error", "error": "Missing S3_BUCKET_NAME env"}, status=500)

    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
        endpoint_url=os.getenv("AWS_S3_ENDPOINT")
    )

    uploaded = []
    missing = []

    # =====================================================
    # Main loop
    # =====================================================
    for entry in items:
        filename = entry.get("filename")
        if not filename:
            continue

        print("\n==========================================")
        print("DEBUG → Processing file:", filename)

        # 1. Extract case name from provided filename
        case_name = dsa.extract_case_name(filename)
        print("DEBUG → Case name:", case_name)

        # 2. Find case folder in DSA
        case_folder = dsa.find_case(case_name)
        if not case_folder:
            print("DEBUG → Case NOT FOUND")
            missing.append({"filename": filename, "reason": "case not found"})
            continue

        # 3. Get Slides folder
        slides_folder = case_folder["subfolders"].get("Slides")
        if not slides_folder:
            print("DEBUG → Slides folder missing")
            missing.append({"filename": filename, "reason": "Slides folder missing"})
            continue

        slides_id = slides_folder["_id"]

        # 4. List all items in Slides
        all_items = dsa.gc.get("item", parameters={"folderId": slides_id, "limit": 0})
        print("DEBUG → Items in Slides:", len(all_items))

        # 5. Filter items that contain files (real slides)
        valid_items = []
        for it in all_items:
            try:
                it_files = dsa.gc.get(f"item/{it['_id']}/files")
            except:
                it_files = []

            if it_files:
                valid_items.append((it, it_files))

        print("DEBUG → Valid items with files:", len(valid_items))

        # 6. Match by item NAME (NOT file object name!)
        match = next(
            (t for t in valid_items if t[0]["name"] == filename),
            None
        )

        if not match:
            print("DEBUG → No valid items matched filename:", filename)
            missing.append({"filename": filename, "reason": "file not found in Slides"})
            continue

        # Correct item
        item, file_list = match
        item_id = item["_id"]
        print("DEBUG → Found valid item_id:", item_id)

        # Important: use the DSA Item Name for S3
        real_name_for_s3 = item["name"]
        print("DEBUG → Using DSA ITEM NAME for S3:", real_name_for_s3)

        # 7. Use FILE OBJECT for downloading
        file_obj = file_list[0]
        file_id  = file_obj["_id"]

        # Download actual binary
        try:
            data = dsa.download_file_bytes(file_id)
            print("DEBUG → Downloaded bytes:", len(data))
        except Exception as e:
            print("DEBUG → DSA download failed:", e)
            missing.append({"filename": filename, "reason": "DSA download failed"})
            continue

        # 8. Upload to S3 using clean case name + real item name
        clean_case = dsa.extract_case_name(real_name_for_s3)
        key = f"{clean_case}/{real_name_for_s3}"

        print("DEBUG → Uploading to S3 key:", key)

        try:
            s3.put_object(Bucket=bucket, Key=key, Body=data)
            uploaded.append(key)
        except Exception as e:
            print("DEBUG → S3 upload failed:", e)
            missing.append({"filename": filename, "reason": "S3 upload failed"})
            continue

    # =====================================================
    # Final response
    # =====================================================
    return JsonResponse({
        "status": "ok",
        "uploaded": uploaded,
        "missing": missing
    })
