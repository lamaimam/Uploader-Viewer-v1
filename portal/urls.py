# uplink/urls.py
from django.urls import path
from uplink.views import index, create_case, upload_to_case, list_case
from uplink.portal import upload_case_files_dsa, upload_case_to_s3  # <-- add upload_case_to_s3

urlpatterns = [
    path("", index, name="index"),

    # Manual create + list
    path("api/cases/create/", create_case, name="create_case"),
    path("api/cases/<str:case_id>/list/", list_case, name="list_case"),

    # Multi-upload (HTML form)
    path("api/cases/<str:case_id>/upload/", upload_to_case, name="upload_to_case"),

    # Webix uploader → real file upload to DSA
    path("api/upload_case_files_dsa/", upload_case_files_dsa, name="upload_case_files_dsa"),

    # NEW: direct upload to S3 (no DSA correlation)
    path("api/upload_case_to_s3/", upload_case_to_s3, name="upload_case_to_s3"),
]
