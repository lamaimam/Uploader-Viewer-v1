# **Digital Slide Case Uploader – README**

## **Overview**

This module implements a full workflow for uploading whole-slide image files from the browser into **Digital Slide Archive (DSA)** and exporting validated slides from DSA into **S3/Spaces**.
It consists of:

* `dsa_client.py` – A helper class for case detection, folder creation, uploading files, and downloading files from DSA.
* `portal.py` – Django endpoints that receive uploads, forward them to DSA, and export selected DSA items to S3.
* `script.js` – The browser UI logic for file selection, deduplication, progress tracking, DSA upload, and S3 export.

---

# **1. `uplink/dsa_client.py`**

### **Purpose**

Provides a clean, structured interface for working with DSA: organizing slides inside case folders, uploading files into the correct location, locating items, deleting items, and downloading file bytes.

### **Main Responsibilities**

* **Configuration**: Reads DSA API URL, collection ID, and API key.
* **Case Name Extraction** (`extract_case_name`)
  Parses filenames to derive consistent case names such as `RQ-25-2-SP25-11726`.
* **Case Management**

  * `find_case` – Locate an existing case folder and its Slides subfolder.
  * `create_case` – Create a new case folder and empty Slides subfolder.
  * `ensure_case_for_filename` – Determine the correct case for a filename and create it if needed.
* **Item Lookup & Deletion**

  * `find_item_in_slides` – Find an item in a Slides folder by filename.
  * `delete_item` – Remove an item from DSA.
* **Uploading**

  * `upload_file_to_slides` – Upload a file into a Slides folder, replacing an existing item with the same filename if present.
  * `upload_case_file` – Convenience wrapper: determine case, locate Slides, remove old item, upload new one.
* **Downloading**

  * `download_file_bytes` – Retrieve raw file bytes from DSA for export to S3.

---

# **2. `uplink/portal.py`**

### **Purpose**

Implements Django REST endpoints used by the browser to push slides to DSA and to export stored slides to S3.

---

## **`upload_case_files_dsa`**

### What it does:

* Receives a slide file from the browser via `POST`.
* Writes the upload to a temporary file.
* Determines which case the file belongs to using `DSAClient`.
* Ensures the case and its Slides folder exist.
* Uploads the file into DSA, replacing any previous item with the same filename.
* Returns the case name and DSA item ID.

---

## **`upload_case_to_s3`**

### What it does:

* Receives a JSON list of filenames and item IDs.
* For each file:

  * Determines the case name.
  * Finds the correct case folder and its Slides folder.
  * Identifies the matching DSA item by item name.
  * Downloads the file bytes from DSA.
  * Uploads the file to S3 using a clean case-based key structure.
* Returns which files were uploaded and which were missing or failed.

---

# **3. `static/script.js`**

### **Purpose**

Implements the entire front-end uploader interface:
file selection, deduplication, UI rendering, progress bars, and communication with the Django endpoints.

### **Main Responsibilities**

#### **File Management**

* Adds files through drag-and-drop or file dialog.
* Normalizes filenames to avoid duplicates.
* Ensures only one entry exists per filename (replace-on-add behavior).
* Provides delete buttons for each file.

#### **Label Detection**

Identifies file type tags (H&E, PD-L1, PD-L1 NC) based on filename.

#### **Rendering**

* Creates visual “file blocks” with name, size, progress bar, and status text.
* Supports filtering by label.

#### **DSA Upload**

* Sends each file to the Django DSA endpoint using `XMLHttpRequest`.
* Tracks progress per file.
* Stores returned DSA item IDs.
* Shows success or failure for each upload.
* Enables S3 upload only when all DSA uploads succeed.

#### **S3 Export**

* Sends a JSON payload linking filenames → item IDs.
* Displays results from the S3 export endpoint.
* Shows warnings if any files were missing.

---------------------------------------
### **How to Run**

### **1. Activate your environment**

```bash
source venv/bin/activate
```

(or `conda activate <env>`)

### **2. Make sure `.env` contains all DSA + S3 variables**

`load_dotenv()` loads them automatically, so no extra steps needed.

### **3. Run migrations (only once)**

```bash
python manage.py migrate
```

### **4. Start Django**

```bash
python manage.py runserver 0.0.0.0:8000
```

(or `runsslserver` if using HTTPS)

### **5. Open the uploader UI in the browser**

```
http://127.0.0.1:8000/<your-uploader-page>/
```

### **6. Use the UI**

* Drag files in
* Click **Upload to DSA**
* After all succeed, click **Upload Case to S3**

### **7. Stop the server**

Press **Ctrl + C**

---
## **Future Work**

Issues:
1. Updating status messages to be UI friendly and synchronized with each step of the loading processes.
2. Making load bar progress move when 'Upload Case to S3" is triggered.
3. No placeholders in DSA unless successfully uploaded.
4. Ensuring there are no temporary files in browser.
