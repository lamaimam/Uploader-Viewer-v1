// =====================================================
// DOM READY
// =====================================================
document.addEventListener("DOMContentLoaded", function () {

console.log("🚀 script.js loaded");

// -----------------------------------------------------
// CONFIG
// -----------------------------------------------------
const uploadDSAUrl = "http://127.0.0.1:8000/api/upload_case_files_dsa/";
const uploadS3Url  = "http://127.0.0.1:8000/api/upload_case_to_s3/";

let lastCaseName = null;
let realFiles = [];   // [{ id, file, normalized, label, dsaItemId }]
let uploadingDSA = false;
let dsaProgress = { done:0, ok:0, total:0 };


// -----------------------------------------------------
// HELPERS
// -----------------------------------------------------
function showStatus(msg, color="#0f172a"){
    const s = document.getElementById("statusMsg");
    s.textContent = msg;
    s.style.color = color;
}

function showError(msg){
    showStatus("❌ " + msg, "#dc2626");
}

function detectLabel(name){
    const n = name.toUpperCase();
    if (n.includes("PDL") || n.includes("PD-L"))
        return n.includes("NC") ? "PDL-1 (NC)" : "PDL-1";
    if (n.includes("H&E") || n.includes("HE."))
        return "H&E";
    return "Unknown";
}

function normalizeFilename(name){
    return name.trim().toLowerCase();
}

function resetBars(){
    document.querySelectorAll(".bar").forEach(b=>{
        b.style.width = "0%";
        b.style.background = "#14b8a6";
    });
    document.querySelectorAll(".status-text").forEach(st=>{
        st.textContent = "";
        st.classList.remove("status-ok","status-fail");
    });
}

function applyFilter(){
    const active = new Set(
        [...document.querySelectorAll(".tag-filter")]
            .filter(cb => cb.checked)
            .map(cb => cb.value)
    );

    document.querySelectorAll(".file-block").forEach(b=>{
        b.style.display = active.has(b.dataset.label) ? "" : "none";
    });
}

function updateLiveCounter(){
    if (!uploadingDSA) {
        if (realFiles.length > 0) {
            showStatus(`Files selected: ${realFiles.length}`, "#0f172a");
        } else {
            showStatus("");
        }
        return;
    }

    let {done,total} = dsaProgress;

    if (total === 0) {
        showError("All files removed.");
        return;
    }

    showStatus(`⏳ Uploading to DSA... (${done}/${total})`);
}


// -----------------------------------------------------
// RENDER FILE BLOCK
// -----------------------------------------------------
function renderFileBlock(obj){
    const file = obj.file;
    const block = document.createElement("div");
    block.className = "file-block";
    block.id        = "file-" + obj.id;
    block.dataset.label = obj.label;

    block.innerHTML = `
        <div class="file-header">
            <div class="file-name">${file.name}</div>
            <div class="file-meta">
                <div class="file-size">${(file.size/1024/1024).toFixed(2)} MB</div>
                <div class="status-text" id="status-${obj.id}"></div>
                <div class="delete-btn" data-id="${obj.id}">&times;</div>
            </div>
        </div>
        <div class="progress">
            <div class="bar" id="bar-${obj.id}"></div>
        </div>
    `;

    document.getElementById("fileList").appendChild(block);
    applyFilter();
    updateLiveCounter();
}


// -----------------------------------------------------
// ADD FILE
// -----------------------------------------------------
function addFile(file){
    const normalized = normalizeFilename(file.name);
    const label      = detectLabel(file.name);
    const id         = webix.uid().toString();

    const idx = realFiles.findIndex(f => f.normalized === normalized);

    if (idx !== -1) {
        document.getElementById("file-"+realFiles[idx].id)?.remove();
        realFiles.splice(idx,1);
    }

    realFiles.push({ id, file, normalized, label, dsaItemId: null });
    renderFileBlock({ id, file, label });
}


// -----------------------------------------------------
// DELETE FILE
// -----------------------------------------------------
document.addEventListener("click", function(e){
    if (!e.target.classList.contains("delete-btn")) return;

    const id = e.target.dataset.id;

    const block = document.getElementById("file-" + id);
    if (block) block.remove();

    const idx = realFiles.findIndex(f => f.id === id);
    if (idx !== -1) realFiles.splice(idx,1);

    if (uploadingDSA) {
        dsaProgress.total = realFiles.length;

        if (dsaProgress.total === 0) {
            uploadingDSA = false;
            showStatus("All files removed.", "#dc2626");
            return;
        }

        if (dsaProgress.done > dsaProgress.total)
            dsaProgress.done = dsaProgress.total;

        updateLiveCounter();
        return;
    }

    updateLiveCounter();
});


// -----------------------------------------------------
// FILTER BAR
// -----------------------------------------------------
document.querySelectorAll(".tag-filter").forEach(cb=>{
    cb.addEventListener("change", applyFilter);
});


// -----------------------------------------------------
// WEBIX UPLOADER
// -----------------------------------------------------
webix.ui({
    view:"uploader",
    id:"uploader",
    autosend:false,
    multiple:true,
    drop:true,
    apiOnly:true,
    on:{
        onBeforeFileAdd:function(item){
            const file = item.file;
            if (!file || file.size === 0) {
                showError(`Cannot add ${file ? file.name : "file"} (0 bytes)`);
                return false;
            }
            addFile(file);
            return false;
        }
    }
});

// Disable overlays
const killOverlay=document.createElement("style");
killOverlay.innerHTML=`
  .webix_upload,.webix_upload_overlay,.webix_overlay,
  .webix_drag_zone,.webix_drag_zone_top {
      display:none!important;
      pointer-events:none!important;
  }
`;
document.head.appendChild(killOverlay);


// -----------------------------------------------------
// DROPZONE
// -----------------------------------------------------
const dropzone=document.getElementById("dropzone");
dropzone.onclick = () => $$("uploader").fileDialog();

dropzone.addEventListener("dragover", e=>{
    e.preventDefault();
    dropzone.classList.add("webix_dropover");
});
dropzone.addEventListener("dragleave", ()=>{
    dropzone.classList.remove("webix_dropover");
});
dropzone.addEventListener("drop", e=>{
    e.preventDefault();
    dropzone.classList.remove("webix_dropover");
    for (const item of e.dataTransfer.items) {
        if (item.kind === "file") {
            const f = item.getAsFile();
            if (!f) continue;
            if (f.size === 0) { showError(`Cannot add ${f.name}`); continue; }
            addFile(f);
        }
    }
});


// -----------------------------------------------------
// DSA UPLOAD (FINAL WORKING VERSION)
// -----------------------------------------------------
document.getElementById("uploadDSABtn").onclick = function() {

    if (realFiles.length === 0) {
        showError("No files selected.");
        return;
    }

    resetBars();
    uploadingDSA = true;
    dsaProgress = { done:0, ok:0, total:realFiles.length };

    showStatus(`⏳ Uploading to DSA... (0/${dsaProgress.total})`);

    realFiles.forEach(fileEntry => {

        const id   = fileEntry.id;
        const file = fileEntry.file;

        if (!document.getElementById("file-" + id)) return;

        const form = new FormData();
        form.append("file", file, file.name);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", uploadDSAUrl, true);

        xhr.upload.onprogress = (e)=>{
            if (e.lengthComputable) {
                document.getElementById("bar-"+id).style.width =
                    (e.loaded / e.total) * 100 + "%";
            }
        };

        xhr.onreadystatechange = ()=>{
            if (xhr.readyState !== 4) return;

            let resp = null;
            try { resp = JSON.parse(xhr.responseText); } catch {}

            const bar = document.getElementById("bar-" + id);
            const st  = document.getElementById("status-"+id);

            console.log("🔥 RAW:", xhr.responseText);
            console.log("🔥 PARSED:", resp);

            if (xhr.status === 200 && resp && resp.status === "ok") {
                console.log("🔥 SUCCESS for", file.name);
                console.log("🔥 item_id =", resp.item_id);

                fileEntry.dsaItemId = resp.item_id;

                bar.style.width = "100%";
                bar.style.background = "#16a34a";
                st.textContent = "Uploaded";
                st.classList.add("status-ok");

                dsaProgress.ok++;
            } else {
                bar.style.background = "#dc2626";
                st.textContent = "Failed";
                st.classList.add("status-fail");
            }

            dsaProgress.done++;

            if (dsaProgress.done < dsaProgress.total) {
                updateLiveCounter();
                return;
            }

            uploadingDSA = false;

            if (dsaProgress.ok === dsaProgress.total) {
                showStatus(`✅ All uploaded (${dsaProgress.ok}/${dsaProgress.total})`,
                    "#16a34a");
                document.getElementById("uploadS3Btn").disabled=false;
            }
            else if (dsaProgress.ok > 0) {
                showStatus(`⚠️ Some failed (${dsaProgress.ok}/${dsaProgress.total})`,
                    "#f59e0b");
            }
            else {
                showError("All uploads failed.");
            }
        };

        xhr.send(form);
    });

};  // <--- CRITICAL: closing onclick handler


// -----------------------------------------------------
// S3 EXPORT (JSON MODE WITH item_id SUPPORT)
// -----------------------------------------------------
document.getElementById("uploadS3Btn").onclick = function() {

    console.log("DEBUG → USING S3 JSON MODE (FIXED)");

    if (realFiles.length === 0) {
        showError("Select files first.");
        return;
    }

    resetBars();
    showStatus("⏳ Checking DSA and uploading to S3...");

    const payload = {
        items: realFiles.map(f => ({
            filename: f.file.name,
            item_id:  f.dsaItemId || null
        }))
    };

    const xhr = new XMLHttpRequest();
    xhr.open("POST", uploadS3Url, true);
    xhr.setRequestHeader("Content-Type", "application/json");

    xhr.onreadystatechange = ()=>{
        if (xhr.readyState !== 4) return;

        let resp=null;
        try { resp = JSON.parse(xhr.responseText); } catch {}

        if (xhr.status === 200 && resp) {

            if (resp.missing && resp.missing.length > 0) {
                const list = resp.missing
                    .map(m => `• ${m.filename} (${m.reason})`)
                    .join("\n");

                showStatus(`⚠️ Some S3 uploads failed:\n${list}`, "#f59e0b");

            } else {
                showStatus("✅ All uploaded to S3.", "#16a34a");
            }

            return;
        }

        showError("S3 upload failed.");
    };

    xhr.send(JSON.stringify(payload));
};


}); // END DOM
