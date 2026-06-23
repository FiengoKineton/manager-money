from __future__ import annotations

import html
import mimetypes
from io import BytesIO
from pathlib import Path

from flask import Blueprint, Response, abort, jsonify, make_response, render_template, send_file, send_from_directory, url_for

from money_manager.config import ALLOWED_DOCUMENT_EXTENSIONS
from money_manager.config.user_paths import user_documents_dir
from money_manager.repositories.documents import (
    document_path,
    folder_path,
    is_allowed_document,
    is_allowed_folder,
    list_files,
)
from money_manager.security.protection_manager import safe_join
from money_manager.security.secure_storage import read_binary_secure

bp = Blueprint("documents", __name__)


@bp.route("/documents-background/<path:filename>")
def documents_background(filename):
    if not is_allowed_document(filename):
        abort(404)
    documents_dir = Path(user_documents_dir())
    safe_path = safe_join(documents_dir, filename)
    if not safe_path.exists() or not safe_path.is_file():
        abort(404)
    data = read_binary_secure(safe_path)
    mimetype = mimetypes.guess_type(safe_path.name)[0] or "application/octet-stream"
    return send_file(BytesIO(data), mimetype=mimetype, as_attachment=False, download_name=safe_path.name, conditional=False, max_age=3600)


@bp.route("/profile-photo")
def profile_photo():
    photo = safe_join(user_documents_dir(), "selfie.jpg")
    if not photo.exists() or not photo.is_file():
        abort(404)
    return send_file(BytesIO(read_binary_secure(photo)), mimetype="image/jpeg", as_attachment=False, download_name="selfie.jpg", conditional=False, max_age=3600)


@bp.route("/documents")
def documents():
    allowed_extensions = sorted(ALLOWED_DOCUMENT_EXTENSIONS)

    return render_template(
        "support/documents.html",
        allowed_extensions=allowed_extensions,
    )


@bp.route("/api/files/<folder>")
def api_files(folder):
    if not is_allowed_folder(folder):
        return jsonify({"files": []})

    return jsonify({"files": list_files(folder)})


@bp.route("/document/<folder>/<path:filename>")
def serve_document(folder, filename):
    path = _safe_document_path(folder, filename)
    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    response = make_response(send_file(BytesIO(read_binary_secure(path)), mimetype=mimetype, as_attachment=False, download_name=path.name, conditional=False))
    response.headers["Content-Disposition"] = f'inline; filename="{path.name}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.route("/document-preview/<folder>/<path:filename>")
def preview_document(folder, filename):
    path = _safe_document_path(folder, filename)
    suffix = path.suffix.lower()
    raw_url = url_for("documents.serve_document", folder=folder, filename=filename)
    title = html.escape(path.name)

    if suffix == ".pdf":
        body = f'<iframe class="doc-preview-frame" src="{raw_url}#toolbar=1&navpanes=0" title="{title}"></iframe>'
    elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}:
        body = f'<div class="doc-image-wrap"><img src="{raw_url}" alt="{title}"></div>'
    elif suffix == ".txt":
        raw = read_binary_secure(path)
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("latin-1", errors="replace")
        body = f'<pre class="doc-text-preview">{html.escape(content)}</pre>'
    else:
        body = f'<p class="doc-preview-empty">Preview unavailable. <a href="{raw_url}" target="_blank" rel="noopener">Open file</a></p>'

    html_page = f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #0f172a; background: #f8fafc; }}
    .doc-preview-shell {{ min-height: 100vh; display: flex; flex-direction: column; }}
    .doc-preview-top {{ display: flex; justify-content: space-between; gap: 1rem; align-items: center; padding: 0.8rem 1rem; background: rgba(255,255,255,0.96); border-bottom: 1px solid #e2e8f0; position: sticky; top: 0; z-index: 5; }}
    .doc-preview-top strong {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .doc-preview-top a {{ color: #2454d6; text-decoration: none; font-weight: 800; white-space: nowrap; }}
    .doc-preview-body {{ flex: 1; min-height: 0; }}
    .doc-preview-frame {{ width: 100%; height: calc(100vh - 56px); border: 0; background: white; }}
    .doc-image-wrap {{ min-height: calc(100vh - 56px); display: grid; place-items: start center; padding: 1.5rem; overflow: auto; }}
    .doc-image-wrap img {{ max-width: 100%; height: auto; border-radius: 18px; box-shadow: 0 18px 45px rgba(15,23,42,0.16); background: white; }}
    .doc-text-preview {{ margin: 0; min-height: calc(100vh - 56px); padding: 1.25rem; white-space: pre-wrap; font: 14px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: white; }}
    .doc-preview-empty {{ padding: 2rem; }}
  </style>
</head>
<body>
  <div class="doc-preview-shell">
    <div class="doc-preview-top"><strong>{title}</strong><a href="{raw_url}" target="_blank" rel="noopener">Open full size</a></div>
    <div class="doc-preview-body">{body}</div>
  </div>
</body>
</html>
"""
    return Response(html_page, mimetype="text/html")


def _safe_document_path(folder: str, filename: str) -> Path:
    if not is_allowed_folder(folder):
        abort(404)
    if not is_allowed_document(filename):
        abort(404)
    try:
        path = document_path(folder, filename)
        base = folder_path(folder).resolve()
    except ValueError:
        abort(404)
    if base not in path.resolve().parents and path.resolve() != base:
        abort(404)
    if not path.exists() or not path.is_file():
        abort(404)
    return path
