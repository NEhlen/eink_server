import base64
import json
import logging
import mimetypes
import os
import re
import sys
import time
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.eink_display import display_image_on_eink
from backend.image_transform.palettes import (
    waveshare_e6_calibrated,
    waveshare_e6_empirical,
    waveshare_e6_ideal,
)
from backend.image_transform.transform_image import transform_image_pair

RAW_DIR = ROOT_DIR / "images_raw"
DITHERED_DIR = ROOT_DIR / "images"
DISPLAY_DIR = ROOT_DIR / "images_display"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp", ".tif", ".tiff"}
PALETTES = {
    "calibrated": waveshare_e6_calibrated,
    "empirical": waveshare_e6_empirical,
    "ideal": waveshare_e6_ideal,
}
XAI_MODEL = "grok-imagine-image"
XAI_GENERATIONS_URL = "https://api.x.ai/v1/images/generations"
XAI_EDITS_URL = "https://api.x.ai/v1/images/edits"
XAI_ASPECT_RATIOS = {"2:3", "3:2"}
RAW_CLEANUP_DAYS = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>E-Ink Image Server</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --text: #1d2329;
      --muted: #65717d;
      --line: #d9dee3;
      --accent: #116a5c;
      --accent-dark: #0b4d43;
      --danger: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 20px; font-weight: 700; }
    main { max-width: 1100px; margin: 0 auto; padding: 24px; }
    .tabs { display: flex; gap: 8px; margin-bottom: 18px; }
    .tab {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 7px;
      cursor: pointer;
      font-weight: 650;
    }
    .tab.active { background: var(--accent); color: white; border-color: var(--accent); }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    .hidden { display: none; }
    .upload-grid {
      display: grid;
      grid-template-columns: minmax(260px, 360px) 1fr;
      gap: 22px;
      align-items: start;
    }
    label { display: block; font-weight: 650; margin-bottom: 8px; }
    input[type="file"], textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      background: #fbfcfd;
      font: inherit;
    }
    textarea {
      min-height: 120px;
      resize: vertical;
    }
    .field { margin-top: 14px; }
    .segmented {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 4px;
      background: #fbfcfd;
    }
    .segmented input {
      inline-size: 1px;
      block-size: 1px;
      opacity: 0;
      position: absolute;
    }
    .segmented label {
      margin: 0;
      min-height: 34px;
      display: grid;
      place-items: center;
      border-radius: 6px;
      color: var(--muted);
      cursor: pointer;
      font-weight: 700;
    }
    .segmented input:checked + label {
      background: var(--accent);
      color: white;
    }
    button {
      border: 1px solid var(--accent);
      background: var(--accent);
      color: white;
      min-height: 40px;
      border-radius: 7px;
      padding: 0 14px;
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary { background: white; color: var(--accent-dark); }
    button.danger { background: white; border-color: var(--danger); color: var(--danger); }
    button:disabled { opacity: 0.55; cursor: wait; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .preview {
      display: grid;
      grid-template-columns: minmax(220px, 380px) minmax(180px, 1fr);
      gap: 18px;
      align-items: start;
    }
    .preview img, .thumb img {
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      background: white;
      image-rendering: auto;
    }
    .meta { color: var(--muted); font-size: 14px; line-height: 1.5; }
    .status { min-height: 22px; margin-top: 12px; font-size: 14px; }
    .status.error { color: var(--danger); }
    .history-tools {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }
    .gallery {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
      gap: 14px;
    }
    .thumb {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: white;
    }
    .thumb-title {
      font-size: 13px;
      font-weight: 700;
      overflow-wrap: anywhere;
      margin: 8px 0 4px;
    }
    @media (max-width: 760px) {
      header { align-items: flex-start; flex-direction: column; }
      main { padding: 16px; }
      .upload-grid, .preview { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>E-Ink Image Server</h1>
    <button class="secondary" id="refreshButton" type="button">Refresh</button>
  </header>
  <main>
    <div class="tabs" role="tablist">
      <button class="tab active" id="uploadTab" type="button">Upload</button>
      <button class="tab" id="generateTab" type="button">Generate</button>
      <button class="tab" id="historyTab" type="button">History</button>
    </div>

    <section class="panel" id="uploadPanel">
      <div class="upload-grid">
        <form id="uploadForm">
          <label for="imageInput">Image</label>
          <input id="imageInput" name="image" type="file" accept="image/*" required>
          <div class="field">
            <label>Browser Preview Palette</label>
            <div class="segmented">
              <input id="paletteCalibrated" name="palette" type="radio" value="calibrated" checked>
              <label for="paletteCalibrated">Calibrated</label>
              <input id="paletteIdeal" name="palette" type="radio" value="ideal">
              <label for="paletteIdeal">Ideal</label>
            </div>
          </div>
          <div class="actions">
            <button id="uploadButton" type="submit">Upload and Dither</button>
          </div>
          <div class="status" id="uploadStatus"></div>
        </form>
        <div id="previewEmpty" class="meta">No image uploaded in this session.</div>
        <div id="preview" class="preview hidden">
          <img id="previewImage" alt="Dithered preview">
          <div>
            <div class="meta" id="previewMeta"></div>
            <div class="actions">
              <button id="displayPreviewButton" type="button">Send to Screen</button>
            </div>
            <div class="status" id="displayStatus"></div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel hidden" id="generatePanel">
      <div class="upload-grid">
        <form id="generateForm">
          <label for="promptInput">Prompt</label>
          <textarea id="promptInput" name="prompt" required></textarea>
          <div class="field">
            <label for="generateImageInput">Source Image</label>
            <input id="generateImageInput" name="image" type="file" accept="image/*">
          </div>
          <div class="field">
            <label>Aspect</label>
            <div class="segmented">
              <input id="aspectPortrait" name="aspect_ratio" type="radio" value="2:3" checked>
              <label for="aspectPortrait">2:3</label>
              <input id="aspectLandscape" name="aspect_ratio" type="radio" value="3:2">
              <label for="aspectLandscape">3:2</label>
            </div>
          </div>
          <div class="field">
            <label>Browser Preview Palette</label>
            <div class="segmented">
              <input id="generatePaletteCalibrated" name="palette" type="radio" value="calibrated" checked>
              <label for="generatePaletteCalibrated">Calibrated</label>
              <input id="generatePaletteIdeal" name="palette" type="radio" value="ideal">
              <label for="generatePaletteIdeal">Ideal</label>
            </div>
          </div>
          <div class="actions">
            <button id="generateButton" type="submit">Generate and Dither</button>
          </div>
          <div class="status" id="generateStatus"></div>
        </form>
        <div id="generatePreviewEmpty" class="meta">No generated image in this session.</div>
        <div id="generatePreview" class="preview hidden">
          <img id="generatePreviewImage" alt="Generated dithered preview">
          <div>
            <div class="meta" id="generatePreviewMeta"></div>
            <div class="actions">
              <button id="displayGeneratedButton" type="button">Send to Screen</button>
            </div>
            <div class="status" id="generateDisplayStatus"></div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel hidden" id="historyPanel">
      <div class="history-tools">
        <div class="meta">Raw source files older than 30 days can be removed without deleting dithered images.</div>
        <div class="actions">
          <div class="segmented">
            <input id="historyPreviewMode" name="history_image_mode" type="radio" value="preview" checked>
            <label for="historyPreviewMode">Preview</label>
            <input id="historyDisplayMode" name="history_image_mode" type="radio" value="display">
            <label for="historyDisplayMode">Display</label>
          </div>
          <button class="secondary" id="cleanupRawButton" type="button">Clean Raw Files</button>
        </div>
      </div>
      <div class="gallery" id="gallery"></div>
      <div class="status" id="historyStatus"></div>
    </section>
  </main>
  <script>
    const uploadTab = document.getElementById('uploadTab');
    const generateTab = document.getElementById('generateTab');
    const historyTab = document.getElementById('historyTab');
    const uploadPanel = document.getElementById('uploadPanel');
    const generatePanel = document.getElementById('generatePanel');
    const historyPanel = document.getElementById('historyPanel');
    const uploadForm = document.getElementById('uploadForm');
    const uploadButton = document.getElementById('uploadButton');
    const uploadStatus = document.getElementById('uploadStatus');
    const preview = document.getElementById('preview');
    const previewEmpty = document.getElementById('previewEmpty');
    const previewImage = document.getElementById('previewImage');
    const previewMeta = document.getElementById('previewMeta');
    const displayPreviewButton = document.getElementById('displayPreviewButton');
    const displayStatus = document.getElementById('displayStatus');
    const generateForm = document.getElementById('generateForm');
    const generateButton = document.getElementById('generateButton');
    const generateStatus = document.getElementById('generateStatus');
    const generatePreview = document.getElementById('generatePreview');
    const generatePreviewEmpty = document.getElementById('generatePreviewEmpty');
    const generatePreviewImage = document.getElementById('generatePreviewImage');
    const generatePreviewMeta = document.getElementById('generatePreviewMeta');
    const displayGeneratedButton = document.getElementById('displayGeneratedButton');
    const generateDisplayStatus = document.getElementById('generateDisplayStatus');
    const refreshButton = document.getElementById('refreshButton');
    const cleanupRawButton = document.getElementById('cleanupRawButton');
    const gallery = document.getElementById('gallery');
    const historyStatus = document.getElementById('historyStatus');
    const historyModeInputs = Array.from(document.querySelectorAll('input[name="history_image_mode"]'));
    let selectedFilename = null;
    let generatedFilename = null;

    function setTab(name) {
      const history = name === 'history';
      const generate = name === 'generate';
      uploadTab.classList.toggle('active', !history && !generate);
      generateTab.classList.toggle('active', generate);
      historyTab.classList.toggle('active', history);
      uploadPanel.classList.toggle('hidden', history || generate);
      generatePanel.classList.toggle('hidden', !generate);
      historyPanel.classList.toggle('hidden', !history);
      if (history) loadHistory();
    }

    function setStatus(node, message, error = false) {
      node.textContent = message;
      node.classList.toggle('error', error);
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    async function api(path, options = {}) {
      const response = await fetch(path, options);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || response.statusText);
      return payload;
    }

    uploadForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      uploadButton.disabled = true;
      setStatus(uploadStatus, 'Uploading and dithering...');
      try {
        const formData = new FormData(uploadForm);
        const result = await api('/api/upload', { method: 'POST', body: formData });
        selectedFilename = result.filename;
        previewImage.src = result.url + '?t=' + Date.now();
        previewMeta.innerHTML = `<strong>${escapeHtml(result.filename)}</strong><br>${result.width} x ${result.height}<br>${escapeHtml(result.palette)} palette<br>${escapeHtml(result.created_at)}`;
        preview.classList.remove('hidden');
        previewEmpty.classList.add('hidden');
        setStatus(uploadStatus, 'Ready to send.');
        await loadHistory();
      } catch (error) {
        setStatus(uploadStatus, error.message, true);
      } finally {
        uploadButton.disabled = false;
      }
    });

    async function displayImage(filename, statusNode, button) {
      button.disabled = true;
      setStatus(statusNode, 'Sending to screen...');
      try {
        await api('/api/display', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename })
        });
        setStatus(statusNode, 'Sent to screen.');
      } catch (error) {
        setStatus(statusNode, error.message, true);
      } finally {
        button.disabled = false;
      }
    }

    async function deleteImage(filename, statusNode, card, button) {
      if (!confirm('Delete this image and its source file?')) return;
      button.disabled = true;
      setStatus(statusNode, 'Deleting...');
      try {
        await api('/api/images/' + encodeURIComponent(filename), { method: 'DELETE' });
        card.remove();
        setStatus(historyStatus, gallery.children.length ? '' : 'No dithered images yet.');
      } catch (error) {
        setStatus(statusNode, error.message, true);
        button.disabled = false;
      }
    }

    async function cleanupRawFiles() {
      cleanupRawButton.disabled = true;
      setStatus(historyStatus, 'Cleaning raw source files...');
      try {
        const result = await api('/api/raw/cleanup', { method: 'POST' });
        setStatus(historyStatus, `Deleted ${result.deleted.length} raw source file${result.deleted.length === 1 ? '' : 's'}.`);
      } catch (error) {
        setStatus(historyStatus, error.message, true);
      } finally {
        cleanupRawButton.disabled = false;
      }
    }

    displayPreviewButton.addEventListener('click', () => {
      if (selectedFilename) displayImage(selectedFilename, displayStatus, displayPreviewButton);
    });

    generateForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      generateButton.disabled = true;
      setStatus(generateStatus, 'Generating and dithering...');
      try {
        const formData = new FormData(generateForm);
        const result = await api('/api/generate', { method: 'POST', body: formData });
        generatedFilename = result.filename;
        generatePreviewImage.src = result.url + '?t=' + Date.now();
        generatePreviewMeta.innerHTML = `<strong>${escapeHtml(result.filename)}</strong><br>${result.width} x ${result.height}<br>${escapeHtml(result.aspect_ratio)} aspect<br>${escapeHtml(result.palette)} palette<br>${escapeHtml(result.created_at)}`;
        generatePreview.classList.remove('hidden');
        generatePreviewEmpty.classList.add('hidden');
        setStatus(generateStatus, 'Ready to send.');
        await loadHistory();
      } catch (error) {
        setStatus(generateStatus, error.message, true);
      } finally {
        generateButton.disabled = false;
      }
    });

    displayGeneratedButton.addEventListener('click', () => {
      if (generatedFilename) displayImage(generatedFilename, generateDisplayStatus, displayGeneratedButton);
    });

    async function loadHistory() {
      setStatus(historyStatus, 'Loading...');
      try {
        const mode = document.querySelector('input[name="history_image_mode"]:checked')?.value || 'preview';
        const result = await api('/api/images?mode=' + encodeURIComponent(mode));
        gallery.innerHTML = '';
        for (const image of result.images) {
          const card = document.createElement('article');
          card.className = 'thumb';
          card.innerHTML = `
            <img src="${escapeHtml(image.url)}" alt="${escapeHtml(image.filename)}">
            <div class="thumb-title">${escapeHtml(image.filename)}</div>
            <div class="meta">${image.width} x ${image.height}<br>${escapeHtml(image.created_at)}</div>
            <div class="actions">
              <button type="button" data-action="display">Send to Screen</button>
              <button class="danger" type="button" data-action="delete">Delete</button>
            </div>
            <div class="status"></div>
          `;
          const button = card.querySelector('[data-action="display"]');
          const deleteButton = card.querySelector('[data-action="delete"]');
          const status = card.querySelector('.status');
          button.addEventListener('click', () => displayImage(image.filename, status, button));
          deleteButton.addEventListener('click', () => deleteImage(image.filename, status, card, deleteButton));
          gallery.appendChild(card);
        }
        setStatus(historyStatus, result.images.length ? '' : 'No dithered images yet.');
      } catch (error) {
        setStatus(historyStatus, error.message, true);
      }
    }

    uploadTab.addEventListener('click', () => setTab('upload'));
    generateTab.addEventListener('click', () => setTab('generate'));
    historyTab.addEventListener('click', () => setTab('history'));
    refreshButton.addEventListener('click', loadHistory);
    cleanupRawButton.addEventListener('click', cleanupRawFiles);
    historyModeInputs.forEach((input) => input.addEventListener('change', loadHistory));
    loadHistory();
  </script>
</body>
</html>
"""


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    DITHERED_DIR.mkdir(parents=True, exist_ok=True)
    DISPLAY_DIR.mkdir(parents=True, exist_ok=True)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, indent=2).encode("utf-8")


def _safe_filename(filename: str) -> str:
    stem = Path(filename).stem.strip().lower()
    stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip(".-")
    return stem or "image"


def _payload_bytes(payload: object) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    raise ValueError("Invalid multipart payload")


def _load_env_var(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value

    for env_path in (Path.cwd() / ".env", ROOT_DIR / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            if key.strip() == name:
                return raw_value.strip().strip("'\"")
    return None


def _dithered_path_from_name(filename: str) -> Path:
    clean = Path(filename).name
    path = (DITHERED_DIR / clean).resolve()
    if path.parent != DITHERED_DIR.resolve():
        raise ValueError("Invalid filename")
    if path.suffix.lower() != ".png":
        raise ValueError("Only stored PNG images can be displayed")
    return path


def _display_path_from_name(filename: str) -> Path:
    clean = Path(filename).name
    path = (DISPLAY_DIR / clean).resolve()
    if path.parent != DISPLAY_DIR.resolve():
        raise ValueError("Invalid filename")
    if path.suffix.lower() != ".png":
        raise ValueError("Only stored PNG images can be displayed")
    return path


def _target_from_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "2:3":
        return (400, 600)
    if aspect_ratio == "3:2":
        return (600, 400)
    raise ValueError("Aspect ratio must be 2:3 or 3:2")


def _delete_image_files(filename: str) -> dict:
    dithered_path = _dithered_path_from_name(filename)
    if not dithered_path.exists():
        raise FileNotFoundError("Image not found")

    deleted = []
    dithered_stem = dithered_path.stem
    raw_stem = dithered_stem.removeprefix("dith_")
    display_path = _display_path_from_name(dithered_path.name)
    raw_candidates = [
        path
        for path in RAW_DIR.iterdir()
        if path.is_file() and path.stem == raw_stem
    ]

    for path in [dithered_path, display_path, *raw_candidates]:
        try:
            path.unlink()
            deleted.append(str(path.relative_to(ROOT_DIR)))
        except FileNotFoundError:
            pass

    return {"deleted": deleted}


def _cleanup_old_raw_files(days: int = RAW_CLEANUP_DAYS) -> dict:
    cutoff = time.time() - (days * 24 * 60 * 60)
    deleted = []
    if not RAW_DIR.exists():
        return {"deleted": deleted, "days": days}

    for path in RAW_DIR.iterdir():
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            deleted.append(path.name)
        except FileNotFoundError:
            continue

    return {"deleted": deleted, "days": days}


def _image_info(path: Path) -> dict:
    stat = path.stat()
    with Image.open(path) as image:
        width, height = image.size
    created_at = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
    return {
        "filename": path.name,
        "url": f"/images/{quote(path.name)}",
        "width": width,
        "height": height,
        "created_at": created_at,
        "size_bytes": stat.st_size,
    }


def _history_image_info(path: Path, mode: str) -> dict:
    info = _image_info(path)
    if mode == "display":
        display_path = _display_path_from_name(path.name)
        if display_path.exists():
            info["url"] = f"/display-images/{quote(display_path.name)}"
        else:
            info["url"] = f"/images/{quote(path.name)}"
            info["missing_display_file"] = True
    return info


def _parse_upload(content_type: str, body: bytes) -> tuple[str, bytes, str]:
    if not content_type.startswith("multipart/form-data"):
        raise ValueError("Expected multipart/form-data")

    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    filename = None
    data = None
    palette_name = "calibrated"
    for part in message.iter_parts():
        if part.get_content_disposition() == "form-data" and part.get_param("name", header="content-disposition") == "image":
            filename = part.get_filename() or "image"
            data = _payload_bytes(part.get_payload(decode=True))
            if not data:
                raise ValueError("Uploaded file is empty")
        elif part.get_content_disposition() == "form-data" and part.get_param("name", header="content-disposition") == "palette":
            payload = _payload_bytes(part.get_payload(decode=True))
            if payload:
                palette_name = payload.decode("utf-8", errors="ignore").strip().lower()
    if filename is None or data is None:
        raise ValueError("Missing image file")
    if palette_name not in PALETTES:
        raise ValueError("Unknown palette")
    return filename, data, palette_name


def _parse_generate_upload(content_type: str, body: bytes) -> tuple[str, str, str, bytes | None, str]:
    if not content_type.startswith("multipart/form-data"):
        raise ValueError("Expected multipart/form-data")

    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    image_data = None
    image_content_type = "image/png"
    prompt = ""
    palette_name = "calibrated"
    aspect_ratio = "2:3"

    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")
        if field_name == "image":
            filename = part.get_filename() or ""
            if not filename:
                continue
            image_data = _payload_bytes(part.get_payload(decode=True))
            image_content_type = part.get_content_type() or mimetypes.guess_type(filename)[0] or "image/png"
            if not image_data:
                raise ValueError("Uploaded file is empty")
        elif field_name == "prompt":
            payload = _payload_bytes(part.get_payload(decode=True))
            if payload:
                prompt = payload.decode("utf-8", errors="ignore").strip()
        elif field_name == "palette":
            payload = _payload_bytes(part.get_payload(decode=True))
            if payload:
                palette_name = payload.decode("utf-8", errors="ignore").strip().lower()
        elif field_name == "aspect_ratio":
            payload = _payload_bytes(part.get_payload(decode=True))
            if payload:
                aspect_ratio = payload.decode("utf-8", errors="ignore").strip()

    if not prompt:
        raise ValueError("Prompt is required")
    if palette_name not in PALETTES:
        raise ValueError("Unknown palette")
    if aspect_ratio not in XAI_ASPECT_RATIOS:
        raise ValueError("Aspect ratio must be 2:3 or 3:2")
    if image_data is not None and not image_content_type.startswith("image/"):
        raise ValueError("Uploaded file must be an image")
    return prompt, aspect_ratio, palette_name, image_data, image_content_type


def _store_upload(filename: str, data: bytes, palette_name: str) -> dict:
    _ensure_dirs()
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        extension = ".png"

    with Image.open(BytesIO(data)) as input_image:
        input_image.load()
        prepared = ImageOps.exif_transpose(input_image)
        if palette_name == "calibrated":
            display, preview = transform_image_pair(
                prepared, waveshare_e6_ideal, waveshare_e6_calibrated
            )
        else:
            preview, display = transform_image_pair(
                prepared, PALETTES[palette_name], waveshare_e6_ideal
            )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{timestamp}-{palette_name}-{_safe_filename(filename)}"
    raw_path = RAW_DIR / f"{base}{extension}"
    dithered_path = DITHERED_DIR / f"dith_{base}.png"
    display_path = DISPLAY_DIR / dithered_path.name

    raw_path.write_bytes(data)
    preview.save(dithered_path)
    display.save(display_path)
    return _image_info(dithered_path) | {"raw_filename": raw_path.name, "palette": palette_name}


def _store_generated_image(
    prompt: str,
    aspect_ratio: str,
    palette_name: str,
    data: bytes,
    source: str = "xai",
) -> dict:
    _ensure_dirs()
    with Image.open(BytesIO(data)) as input_image:
        input_image.load()
        prepared = ImageOps.exif_transpose(input_image)
        image_format = (prepared.format or input_image.format or "png").lower()
        if image_format == "jpeg":
            image_format = "jpg"
        target = _target_from_aspect_ratio(aspect_ratio)
        if palette_name == "calibrated":
            display, preview = transform_image_pair(
                prepared, waveshare_e6_ideal, waveshare_e6_calibrated, target=target
            )
        else:
            preview, display = transform_image_pair(
                prepared, PALETTES[palette_name], waveshare_e6_ideal, target=target
            )

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    aspect_token = aspect_ratio.replace(":", "x")
    base = f"{timestamp}-{source}-{aspect_token}-{palette_name}-{_safe_filename(prompt)[:80]}"
    raw_path = RAW_DIR / f"{base}.{image_format}"
    dithered_path = DITHERED_DIR / f"dith_{base}.png"
    display_path = DISPLAY_DIR / dithered_path.name

    raw_path.write_bytes(data)
    preview.save(dithered_path)
    display.save(display_path)
    return _image_info(dithered_path) | {
        "raw_filename": raw_path.name,
        "palette": palette_name,
        "aspect_ratio": aspect_ratio,
        "prompt": prompt,
    }


def _read_xai_image_response(body: bytes) -> bytes:
    response_payload = json.loads(body)
    image_data = response_payload.get("data", [{}])[0]
    if image_data.get("b64_json"):
        return base64.b64decode(image_data["b64_json"])
    if image_data.get("url"):
        with urlopen(image_data["url"], timeout=120) as image_response:
            return image_response.read()
    raise RuntimeError("xAI response did not include image data")


def _generate_xai_image(prompt: str, aspect_ratio: str) -> bytes:
    api_key = _load_env_var("XAI_API_KEY")
    if not api_key:
        raise ValueError("Missing XAI_API_KEY in environment or .env")

    payload = {
        "model": XAI_MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "b64_json",
    }
    request = Request(
        XAI_GENERATIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            body = response.read()
    except Exception as exc:
        raise RuntimeError(f"xAI request failed: {exc}") from exc

    return _read_xai_image_response(body)


def _style_transfer_xai_image(
    source_image: bytes,
    source_content_type: str,
    prompt: str,
    aspect_ratio: str,
) -> bytes:
    api_key = _load_env_var("XAI_API_KEY")
    if not api_key:
        raise ValueError("Missing XAI_API_KEY in environment or .env")

    encoded_image = base64.b64encode(source_image).decode("ascii")
    payload = {
        "model": XAI_MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "b64_json",
        "image": {
            "url": f"data:{source_content_type};base64,{encoded_image}",
            "type": "image_url",
        },
    }
    request = Request(
        XAI_EDITS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            body = response.read()
    except Exception as exc:
        raise RuntimeError(f"xAI style transfer request failed: {exc}") from exc

    return _read_xai_image_response(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "EInkServer/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif parsed.path == "/api/images":
            self._handle_list_images(parsed.query)
        elif parsed.path.startswith("/images/"):
            self._handle_static_image(parsed.path.removeprefix("/images/"))
        elif parsed.path.startswith("/display-images/"):
            self._handle_static_display_image(parsed.path.removeprefix("/display-images/"))
        else:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/upload":
            self._handle_upload()
        elif parsed.path == "/api/generate":
            self._handle_generate()
        elif parsed.path == "/api/raw/cleanup":
            self._handle_cleanup_raw()
        elif parsed.path == "/api/display":
            self._handle_display()
        else:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/images/"):
            self._handle_delete_image(parsed.path.removeprefix("/api/images/"))
        else:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _handle_list_images(self, query: str = "") -> None:
        _ensure_dirs()
        mode = parse_qs(query).get("mode", ["preview"])[0]
        if mode not in {"preview", "display"}:
            mode = "preview"
        images = []
        for path in sorted(DITHERED_DIR.glob("*.png"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                images.append(_history_image_info(path, mode))
            except (OSError, UnidentifiedImageError):
                logger.exception("Skipping unreadable image %s", path)
        self._send_json({"images": images})

    def _handle_static_image(self, raw_name: str) -> None:
        try:
            path = _dithered_path_from_name(unquote(raw_name))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if not path.exists():
            self._send_json({"error": "Image not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send_bytes(path.read_bytes(), content_type)

    def _handle_static_display_image(self, raw_name: str) -> None:
        try:
            path = _display_path_from_name(unquote(raw_name))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if not path.exists():
            self._send_json({"error": "Image not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send_bytes(path.read_bytes(), content_type)

    def _handle_delete_image(self, raw_name: str) -> None:
        try:
            result = _delete_image_files(unquote(raw_name))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except FileNotFoundError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        except OSError as exc:
            logger.exception("Delete failed")
            self._send_json({"error": f"Delete failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(result)

    def _handle_cleanup_raw(self) -> None:
        try:
            result = _cleanup_old_raw_files()
        except OSError as exc:
            logger.exception("Raw cleanup failed")
            self._send_json({"error": f"Raw cleanup failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(result)

    def _handle_upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length"}, HTTPStatus.BAD_REQUEST)
            return
        if length <= 0:
            self._send_json({"error": "Upload body is empty"}, HTTPStatus.BAD_REQUEST)
            return
        if length > MAX_UPLOAD_BYTES:
            self._send_json({"error": "Upload is too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        try:
            filename, data, palette_name = _parse_upload(self.headers.get("Content-Type", ""), self.rfile.read(length))
            info = _store_upload(filename, data, palette_name)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(info, HTTPStatus.CREATED)

    def _handle_generate(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"error": "Invalid Content-Length"}, HTTPStatus.BAD_REQUEST)
            return
        if length <= 0:
            self._send_json({"error": "Upload body is empty"}, HTTPStatus.BAD_REQUEST)
            return
        if length > MAX_UPLOAD_BYTES:
            self._send_json({"error": "Upload is too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        try:
            prompt, aspect_ratio, palette_name, source_data, content_type = _parse_generate_upload(
                self.headers.get("Content-Type", ""), self.rfile.read(length)
            )
            if source_data is None:
                image_bytes = _generate_xai_image(prompt, aspect_ratio)
                source = "xai"
            else:
                image_bytes = _style_transfer_xai_image(source_data, content_type, prompt, aspect_ratio)
                source = "xai-style"
            info = _store_generated_image(prompt, aspect_ratio, palette_name, image_bytes, source=source)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except (OSError, UnidentifiedImageError, RuntimeError, json.JSONDecodeError) as exc:
            logger.exception("xAI generation failed")
            self._send_json({"error": f"xAI generation failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(info, HTTPStatus.CREATED)

    def _handle_display(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            path = _dithered_path_from_name(str(payload.get("filename", "")))
            if not path.exists():
                self._send_json({"error": "Image not found"}, HTTPStatus.NOT_FOUND)
                return
            display_path = _display_path_from_name(path.name)
            display_image_on_eink(display_path if display_path.exists() else path)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            logger.exception("Display failed")
            self._send_json({"error": f"Display failed: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json({"ok": True})

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(_json_bytes(payload), "application/json; charset=utf-8", status)

    def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "0.0.0.0", port: int = 8000) -> None:
    _ensure_dirs()
    cleanup_result = _cleanup_old_raw_files()
    if cleanup_result["deleted"]:
        logger.info("Deleted %d raw source files older than %d days", len(cleanup_result["deleted"]), cleanup_result["days"])
    server = ThreadingHTTPServer((host, port), Handler)
    logger.info("Serving on http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping")
    finally:
        server.server_close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    run(args.host, args.port)


if __name__ == "__main__":
    main()
