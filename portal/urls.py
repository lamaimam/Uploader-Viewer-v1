from django.urls import path
from uplink.views import index, create_case, upload_to_case, list_case
from uplink.portal import upload_case_files_dsa

urlpatterns = [
    path("", index, name="index"),

    # Manual create + list
    path("api/cases/create/", create_case, name="create_case"),
    path("api/cases/<str:case_id>/list/", list_case, name="list_case"),

    # Multi-upload (HTML form)
    path("api/cases/<str:case_id>/upload/", upload_to_case, name="upload_to_case"),

    # Webix uploader → real file upload
    path("api/upload_case_files_dsa/", upload_case_files_dsa, name="upload_case_files_dsa"),
]
