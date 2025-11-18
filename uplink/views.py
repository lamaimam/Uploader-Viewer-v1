# uplink/views.py
import os
import tempfile
import uuid
from typing import List, Tuple

from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .dsa_client import DSAClient


# ---------------------------------------------------------------
# INDEX VIEW (serves index.html)
# ---------------------------------------------------------------
def index(request):
    return render(request, "index.html")


# ---------------------------------------------------------------
# CREATE CASE (manual create)
# ---------------------------------------------------------------
@csrf_exempt
@require_http_methods(["POST"])
def create_case(request):
    """Create a new case manually."""
    name = request.POST.get("case_name", "Untitled-Case")

    dsa = DSAClient()   # service API key in env
    case = dsa.create_case(
        case_name=name,
        extra_meta={"source": "LIMS", "status": "Submitted"},
    )

    return JsonResponse({
        "case_folder_id": case["_id"],
        "slides_folder_id": case["subfolders"]["Slides"]["_id"],
        "case_url": f"{dsa.cfg['web']}/#folder/{case['_id']}",
    })


# ---------------------------------------------------------------
# MULTI-FILE UPLOAD (HTML multi-upload)
# ---------------------------------------------------------------
@csrf_exempt
@require_http_methods(["POST"])
def upload_to_case(request, case_id: str):
    """Upload one or more files to an existing case."""
    slides_folder_id = request.POST.get("slides_folder_id")
    if not slides_folder_id:
        return HttpResponseBadRequest("Missing slides_folder_id")

    files = request.FILES.getlist("files")
    if not files:
        return HttpResponseBadRequest("No files uploaded")

    paths: List[Tuple[str, str]] = []

    for f in files:
        fd, path = tempfile.mkstemp(prefix="upl_", suffix=f"_{f.name}")
        with os.fdopen(fd, "wb") as out:
            for chunk in f.chunks():
                out.write(chunk)
        paths.append((f.name, path))

    dsa = DSAClient()
    ticket = uuid.uuid4().hex

    try:
        items = dsa.upload_files_simple(slides_folder_id, paths, ticket)
        item_ids = [it["_id"] for it in items]

        return JsonResponse({
            "ticket": ticket,
            "case_folder_id": case_id,
            "slides_folder_id": slides_folder_id,
            "item_ids": item_ids,
        })

    finally:
        for _, p in paths:
            try:
                os.remove(p)
            except:
                pass


# ---------------------------------------------------------------
# LIST ITEMS (List slides inside a case)
# ---------------------------------------------------------------
@require_http_methods(["GET"])
def list_case(request, case_id: str):
    """List items inside case’s Slides folder."""
    slides_folder_id = request.GET.get("slides_folder_id")
    if not slides_folder_id:
        return HttpResponseBadRequest("slides_folder_id required")

    dsa = DSAClient()
    items = dsa.list_items_in_folder(slides_folder_id)
    return JsonResponse(items, safe=False)
