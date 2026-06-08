from flask import Blueprint, abort, jsonify, render_template, send_from_directory

from money_manager.config import ALLOWED_DOCUMENT_EXTENSIONS, DOCUMENTS_DIR
from money_manager.repositories.documents import (
    is_allowed_document,
    is_allowed_folder,
    list_files,
)

bp = Blueprint("documents", __name__)


@bp.route("/documents-background/<path:filename>")
def documents_background(filename):
    # Do not expose arbitrary files from the documents directory.
    if not is_allowed_document(filename):
        abort(404)

    return send_from_directory(DOCUMENTS_DIR, filename)


@bp.route("/documents")
def documents():
    allowed_extensions = sorted(ALLOWED_DOCUMENT_EXTENSIONS)

    return render_template(
        "documents.html",
        allowed_extensions=allowed_extensions,
    )


@bp.route("/api/files/<folder>")
def api_files(folder):
    if not is_allowed_folder(folder):
        return jsonify({"files": []})

    return jsonify({"files": list_files(folder)})


@bp.route("/document/<folder>/<path:filename>")
def serve_document(folder, filename):
    if not is_allowed_folder(folder):
        return "Invalid folder", 400

    if not is_allowed_document(filename):
        abort(404)

    return send_from_directory(DOCUMENTS_DIR / folder, filename)