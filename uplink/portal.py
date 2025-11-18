# uplink/portal.py
import os
import tempfile

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .dsa_client import DSAClient


@csrf_exempt
def upload_case_files_dsa(request):
    """
    Receive a single real file from the front-end and push it to DSA.

    - Ensures the uploaded file is non-empty on disk
    - Uses DSAClient.upload_case_file to:
      * derive case name from filename (ID prefix)
      * find/create the case
      * upload into its 'Slides' subfolder
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"error": "no file"}, status=400)

    filename = f.name
    size = f.size
    print("DEBUG → Django received:", filename, "size:", size)

    # Write to temporary file
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    with open(tmp_path, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)

    # Double-check real size on disk (extra guard)
    disk_size = os.path.getsize(tmp_path)
    print("DEBUG → Written temp file:", tmp_path, "disk_size:", disk_size)

    if disk_size == 0:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JsonResponse({"error": "zero-byte file on disk"}, status=400)

    try:
        dsa = DSAClient()

        # Let DSAClient handle case grouping based on filename
        case_name, item_id = dsa.upload_case_file(tmp_path, filename)

        return JsonResponse({
            "status": "ok",
            "case": case_name,
            "filename": filename,
            "bytes": disk_size,
            "item_id": item_id,
        })

    except Exception as e:
        print("ERROR in upload_case_files_dsa:", e)
        return JsonResponse({"error": str(e)}, status=500)

    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
