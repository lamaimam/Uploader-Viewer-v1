# uplink/portal.py
import os
import tempfile
from django.conf import settings

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .dsa_client import DSAClient
from dotenv import load_dotenv
load_dotenv()

@csrf_exempt
def upload_case_files_dsa(request):
    """
    Receive a single file from the front-end and push it to DSA.

    IMPORTANT:
    - Only return {"status": "ok"} if DSA upload **really** succeeded.
    - If anything goes wrong, return HTTP 500 + {"status": "error", "error": "..."}.
    """
    if request.method != "POST":
        return JsonResponse({"status": "error", "error": "POST required"}, status=405)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"status": "error", "error": "no file"}, status=400)

    filename = f.name
    size = f.size
    print("DEBUG → Django received:", filename, "size:", size)

    # Write to temporary file
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    with open(tmp_path, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)

    disk_size = os.path.getsize(tmp_path)
    print("DEBUG → Written temp file:", tmp_path, "disk_size:", disk_size)

    if disk_size == 0:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JsonResponse({"status": "error", "error": "zero-byte file on disk"}, status=400)

    try:
        dsa = DSAClient()

        # This will raise if upload fails OR if remote file size is invalid
        case_name, item_id = dsa.upload_case_file(tmp_path, filename)

    except Exception as e:
        # VERY IMPORTANT: any upload/verification error ends up here
        print("ERROR in upload_case_files_dsa:", repr(e))
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JsonResponse(
            {"status": "error", "error": str(e)},
            status=500,
        )

    # Only if we reach here did the upload & verification succeed
    try:
        os.remove(tmp_path)
    except OSError:
        pass

    return JsonResponse({
        "status": "ok",
        "case": case_name,
        "filename": filename,
        "bytes": disk_size,
        "item_id": item_id,
    }, status=200)

# Optional: real S3 upload if configured
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    _HAS_BOTO3 = True
except ImportError:
    _HAS_BOTO3 = False

@csrf_exempt
def upload_case_to_s3(request):
    """
    Direct S3 upload using ONLY these environment variables:

        AWS_ACCESS_KEY_ID
        AWS_SECRET_ACCESS_KEY
        AWS_DEFAULT_REGION
        S3_BUCKET_NAME

    No other variable names will be used.
    """

    if request.method != "POST":
        return JsonResponse({"status": "error", "error": "POST required"}, status=405)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"status": "error", "error": "no file"}, status=400)

    filename = f.name
    size = f.size
    print("DEBUG → S3 endpoint received:", filename, "size:", size)

    # Write temp file
    tmp_path = os.path.join(tempfile.gettempdir(), filename)
    with open(tmp_path, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)

    disk_size = os.path.getsize(tmp_path)
    print("DEBUG → S3 temp file:", tmp_path, "disk_size:", disk_size)

    if disk_size == 0:
        os.remove(tmp_path)
        return JsonResponse({"status": "error", "error": "zero-byte file on disk"}, status=400)

    # ---- Naming logic ----
    case_name = DSAClient.extract_case_name(filename)
    s3_key = f"{case_name}/{filename}"
    print("DEBUG → Derived case_name:", case_name, "→ S3 key:", s3_key)

    # ---- S3 CONFIG using ONLY YOUR VARIABLE NAMES ----
    bucket     = os.getenv("S3_BUCKET_NAME")
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    region     = os.getenv("AWS_DEFAULT_REGION")
    endpoint   = os.getenv("AWS_ENDPOINT_URL")  # optional (can be None)

    print("DEBUG → S3 config resolved:",
          "bucket=", bucket,
          "access_key set=", bool(access_key),
          "secret_key set=", bool(secret_key),
          "region=", region,
          "endpoint=", endpoint)

    # Strict: require all 4 variables
    if not (bucket and access_key and secret_key and region):
        os.remove(tmp_path)
        return JsonResponse(
            {"status": "error",
             "error": "S3 config missing: require S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION"},
            status=500,
        )

    # ---- Real S3 upload ----
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as e:
        os.remove(tmp_path)
        return JsonResponse({"status": "error", "error": f"boto3 not installed: {e}"}, status=500)

    s3 = boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint,  # None for AWS, custom URL for DO Spaces/MinIO
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    try:
        print(f"DEBUG → Uploading {tmp_path} to S3 bucket={bucket}, key={s3_key}")
        s3.upload_file(tmp_path, bucket, s3_key)
    except (BotoCoreError, ClientError) as e:
        print("ERROR → S3 upload failed:", repr(e))
        os.remove(tmp_path)
        return JsonResponse({"status": "error", "error": f"S3 upload failed: {e}"}, status=500)

    os.remove(tmp_path)

    return JsonResponse({
        "status": "ok",
        "filename": filename,
        "bytes": disk_size,
        "case": case_name,
        "bucket": bucket,
        "s3_key": s3_key,
    }, status=200)
