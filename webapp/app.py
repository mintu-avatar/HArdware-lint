"""
webapp/app.py
=============
Flask web frontend for Hardware-Lint — SonarQube-style dashboard.
Session-only storage (in-memory), resets when the server restarts.
"""

from __future__ import annotations
import os
import sys
import tempfile
import shutil
import uuid

from flask import Flask, render_template, request, jsonify, session

# ---- make the project root importable ----
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engine.scanner import scan
from engine.rule_base import get_all_rules

# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.urandom(32)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ALLOWED_EXTENSIONS = {".v", ".sv", ".vh", ".svh", ".vams", ".va"}

# ---------------------------------------------------------------------------
# In-memory session store  (no DB — cleared on restart)
# ---------------------------------------------------------------------------
_store: dict[str, dict] = {}


def _sid() -> str:
    """Return (and lazily create) the session id."""
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def _bucket() -> dict:
    """Return the current session's data bucket."""
    sid = _sid()
    if sid not in _store:
        _store[sid] = {"files": [], "findings": [], "file_contents": {}}
    return _store[sid]


def _allowed(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No files selected"}), 400

    bucket = _bucket()
    tmpdir = tempfile.mkdtemp(prefix="hwlint_")
    new_findings: list[dict] = []

    try:
        for uf in files:
            if not uf.filename or not _allowed(uf.filename):
                continue
            # Sanitise the filename: keep only the basename, strip path chars
            safe_name = os.path.basename(uf.filename).replace("..", "")
            fpath = os.path.join(tmpdir, safe_name)
            uf.save(fpath)

            # Store source text for the viewer
            with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                bucket["file_contents"][safe_name] = fh.read()

            result = scan(fpath)
            for f in result.findings:
                entry = {
                    "file": safe_name,
                    "line": f.line,
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "category": f.category,
                    "description": f.description,
                    "snippet": f.snippet,
                    "suggestion": f.suggestion,
                }
                new_findings.append(entry)

            if safe_name not in bucket["files"]:
                bucket["files"].append(safe_name)

        bucket["findings"].extend(new_findings)
        return jsonify({
            "success": True,
            "new_findings": len(new_findings),
            "summary": _summary(bucket),
            "findings": bucket["findings"],
        })
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route("/api/results")
def api_results():
    bucket = _bucket()
    return jsonify({
        "summary": _summary(bucket),
        "findings": bucket["findings"],
    })


@app.route("/api/source/<filename>")
def api_source(filename):
    """Return the stored source text for the in-browser viewer."""
    safe = os.path.basename(filename)
    bucket = _bucket()
    text = bucket.get("file_contents", {}).get(safe)
    if text is None:
        return jsonify({"error": "File not found in session"}), 404
    return jsonify({"filename": safe, "source": text})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    sid = session.pop("sid", None)
    if sid and sid in _store:
        del _store[sid]
    return jsonify({"success": True})


@app.route("/api/rules")
def api_rules():
    rules = []
    for r in get_all_rules():
        rules.append({
            "rule_id": r.rule_id,
            "category": r.category,
            "severity": r.severity,
            "description": r.description,
        })
    return jsonify({"rules": rules, "total": len(rules)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _summary(bucket: dict) -> dict:
    findings = bucket["findings"]
    files = bucket["files"]
    errors   = sum(1 for f in findings if f["severity"] == "ERROR")
    warnings = sum(1 for f in findings if f["severity"] == "WARNING")
    infos    = sum(1 for f in findings if f["severity"] == "INFO")

    cats: dict[str, dict] = {}
    for f in findings:
        c = f["category"]
        if c not in cats:
            cats[c] = {"ERROR": 0, "WARNING": 0, "INFO": 0, "total": 0}
        cats[c][f["severity"]] += 1
        cats[c]["total"] += 1

    # Per-file breakdown
    per_file: dict[str, dict] = {}
    for f in findings:
        fn = f["file"]
        if fn not in per_file:
            per_file[fn] = {"ERROR": 0, "WARNING": 0, "INFO": 0, "total": 0}
        per_file[fn][f["severity"]] += 1
        per_file[fn]["total"] += 1

    # Rules validated depend on scanned file types:
    # - AMS files (.vams/.va) run only AMS rules
    # - RTL files run only non-AMS rules
    # - Mixed sessions validate the union of both sets
    ams_exts = {".vams", ".va"}
    has_ams = False
    has_non_ams = False
    for fn in files:
        ext = os.path.splitext(fn)[1].lower()
        if ext in ams_exts:
            has_ams = True
        else:
            has_non_ams = True

    all_rules = get_all_rules()
    ams_rules = sum(1 for r in all_rules if r.category == "AMS")
    non_ams_rules = len(all_rules) - ams_rules

    if has_ams and has_non_ams:
        rules_active = len(all_rules)
    elif has_ams:
        rules_active = ams_rules
    elif has_non_ams:
        rules_active = non_ams_rules
    else:
        rules_active = 0

    return {
        "total": len(findings),
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "files_scanned": len(files),
        "files": files,
        "quality_gate": "PASSED" if errors == 0 else "FAILED",
        "categories": cats,
        "per_file": per_file,
        "rules_active": rules_active,
    }


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("  Hardware-Lint  ·  Web Dashboard")
    print("  http://127.0.0.1:5000")
    app.run(debug=True, host="127.0.0.1", port=5000)
