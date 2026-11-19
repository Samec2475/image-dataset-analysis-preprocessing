import os
import uuid
import shutil
import zipfile
import threading

from flask import Flask, request, jsonify, render_template, send_file, abort

app = Flask(__name__)

UPLOAD_BASE = "uploads"
RUNS_BASE = "runs"

os.makedirs(UPLOAD_BASE, exist_ok=True)
os.makedirs(RUNS_BASE, exist_ok=True)

# Thread-safe in-memory run store
_runs_lock = threading.Lock()
_runs = {}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _update_run(run_id, **kwargs):
    with _runs_lock:
        if run_id in _runs:
            _runs[run_id].update(kwargs)


def _get_run(run_id):
    with _runs_lock:
        return dict(_runs[run_id]) if run_id in _runs else None


def _make_log_callback(run_id):
    def callback(msg):
        with _runs_lock:
            if run_id in _runs:
                _runs[run_id]["logs"].append(str(msg))
    return callback


def _run_pipeline_thread(run_id, data_path, run_similarity):
    """Background thread that executes the pipeline."""
    from pipeline import run_pipeline

    run = _get_run(run_id)
    processed_path = run["processed_path"]
    report_path = run["report_path"]
    log_cb = _make_log_callback(run_id)

    _update_run(run_id, status="running")

    try:
        results = run_pipeline(
            data_path=data_path,
            processed_path=processed_path,
            report_path=report_path,
            run_similarity=run_similarity,
            log_callback=log_cb,
        )

        if results is None:
            _update_run(run_id, status="error", error="Pipeline returned no results. Check that the dataset folder has valid class sub-folders.")
        else:
            # Sanitise results so they are JSON-serialisable
            safe_results = _sanitise_results(results)
            _update_run(run_id, status="done", results=safe_results)

    except Exception as exc:
        _update_run(run_id, status="error", error=str(exc))


def _sanitise_results(results):
    """Strip any non-JSON-serialisable values from pipeline results."""
    evaluation = dict(results.get("evaluation", {}))
    classes = results.get("classes", {})
    quality_records = []

    for rec in results.get("quality_records", []):
        q = {}
        for k, v in rec.items():
            if isinstance(v, list):
                q[k] = [str(i) for i in v]
            elif isinstance(v, (str, int, float, bool)) or v is None:
                q[k] = v
            else:
                q[k] = str(v)
        quality_records.append(q)

    image_records = []
    for rec in results.get("image_records", []):
        r = {}
        for k, v in rec.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                r[k] = v
            else:
                r[k] = str(v)
        image_records.append(r)

    sim = results.get("similarity_analysis", {})
    safe_sim = {
        "status": sim.get("status", ""),
        "similar_pairs": sim.get("similar_pairs", 0),
        "message": sim.get("message", ""),
        "pairs": [
            {k: v for k, v in pair.items() if isinstance(v, (str, int, float, bool))}
            for pair in sim.get("pairs", [])
        ]
    }

    return {
        "evaluation": evaluation,
        "classes": classes,
        "quality_records": quality_records,
        "image_records": image_records,
        "similarity_analysis": safe_sim,
    }


def _resolve_dataset_path(path):
    """Return absolute path, defaulting to 'data' if not provided."""
    if not path:
        path = "data"
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    return path


SUPPORTED_FORMATS = (".jpg", ".jpeg", ".png")


def _list_classes(directory):
    """Return sorted sub-folder names inside directory (class folders)."""
    if not os.path.isdir(directory):
        return []
    return sorted([
        f for f in os.listdir(directory)
        if os.path.isdir(os.path.join(directory, f))
          and not f.startswith("__")   # ignore __MACOSX etc.
          and not f.startswith(".")    # ignore hidden folders
    ])


def _folder_has_images(directory):
    """Return True if directory directly contains at least one image file."""
    try:
        return any(
            f.lower().endswith(SUPPORTED_FORMATS)
            for f in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, f))
        )
    except OSError:
        return False


def _find_dataset_root(base_dir):
    """
    Walk up to 2 levels deep to find the directory whose sub-folders
    contain image files — that is the dataset root (class-level parent).

    Handles all common ZIP structures:
      zip → cats/ + dogs/ → images          (base_dir is root)
      zip → dataset/ → cats/ + dogs/ → images  (one level nested)
      zip → dataset/ → images                  (single class, flat)
    """
    def classes_with_images(d):
        """Sub-folders of d that actually contain image files."""
        return [
            sub for sub in os.listdir(d)
            if not sub.startswith("__") and not sub.startswith(".")
            and os.path.isdir(os.path.join(d, sub))
            and _folder_has_images(os.path.join(d, sub))
        ]

    # Level 0 — base_dir itself has class folders with images
    if classes_with_images(base_dir):
        return base_dir

    # Level 1 — one folder deep (e.g. zip wraps everything in a single folder)
    for entry in sorted(os.listdir(base_dir)):
        candidate = os.path.join(base_dir, entry)
        if entry.startswith("__") or entry.startswith("."):
            continue
        if os.path.isdir(candidate) and classes_with_images(candidate):
            return candidate

    # Fallback — return base_dir and let the pipeline report the error
    return base_dir


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------

@app.route("/api/classes")
def api_classes():
    """List class folders inside a given local directory."""
    raw_path = request.args.get("path", "")
    directory = _resolve_dataset_path(raw_path)

    if not os.path.isdir(directory):
        return jsonify({"error": "Directory not found", "classes": [], "path": directory})

    classes = _list_classes(directory)
    return jsonify({"classes": classes, "path": directory, "error": None})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Accept a ZIP file, extract it, and return a data_path and class list."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]

    if not file.filename.lower().endswith(".zip"):
        return jsonify({"error": "Only .zip files are accepted"}), 400

    upload_id = str(uuid.uuid4())
    extract_dir = os.path.join(UPLOAD_BASE, upload_id)
    os.makedirs(extract_dir, exist_ok=True)
    zip_path = os.path.join(extract_dir, "upload.zip")

    try:
        file.save(zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Security: reject path traversal entries
            for member in zf.namelist():
                if ".." in member or member.startswith(("/", "\\")):
                    shutil.rmtree(extract_dir, ignore_errors=True)
                    return jsonify({"error": "ZIP contains unsafe paths"}), 400

            zf.extractall(extract_dir)

        os.remove(zip_path)

        # Debug: print what was extracted
        print("\n--- ZIP EXTRACTION DEBUG ---")
        for root, dirs, files in os.walk(extract_dir):
            level = root.replace(extract_dir, "").count(os.sep)
            indent = "  " * level
            print(f"{indent}{os.path.basename(root)}/")
            for f in files[:5]:
                print(f"{indent}  {f}")
        print("----------------------------\n")

        # Intelligently find the directory that contains the class folders
        data_path = _find_dataset_root(extract_dir)
        classes   = _list_classes(data_path)

        print(f"Detected data_path: {data_path}")
        print(f"Detected classes:   {classes}")

        if not classes:
            found = []
            for root, dirs, files in os.walk(extract_dir):
                for d in dirs:
                    found.append(os.path.relpath(os.path.join(root, d), extract_dir))
            shutil.rmtree(extract_dir, ignore_errors=True)
            detail = f"Folders inside ZIP: {found[:10]}" if found else "ZIP appears empty."
            return jsonify({
                "error": (
                    "No class sub-folders with images were found. "
                    "Expected: cats/ and dogs/ folders containing images. "
                    f"({detail})"
                )
            }), 400

        return jsonify({
            "upload_id": upload_id,
            "data_path": data_path,
            "classes":   classes,
            "error":     None
        })

    except zipfile.BadZipFile:
        shutil.rmtree(extract_dir, ignore_errors=True)
        return jsonify({"error": "Invalid or corrupted ZIP file"}), 400
    except Exception as exc:
        shutil.rmtree(extract_dir, ignore_errors=True)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/run", methods=["POST"])
def api_run():
    """Start a pipeline run in a background thread and return a run_id."""
    body = request.get_json(silent=True) or {}

    data_path = _resolve_dataset_path(body.get("data_path", ""))
    run_similarity = bool(body.get("run_similarity", False))

    if not os.path.isdir(data_path):
        return jsonify({"error": f"Dataset directory not found: {data_path}"}), 400

    if not _list_classes(data_path):
        return jsonify({"error": "No class sub-folders found in the dataset directory"}), 400

    run_id = str(uuid.uuid4())
    run_base = os.path.join(RUNS_BASE, run_id)
    processed_path = os.path.join(run_base, "processed_data")
    report_path = os.path.join(run_base, "reports")

    os.makedirs(run_base, exist_ok=True)

    with _runs_lock:
        _runs[run_id] = {
            "status": "pending",
            "logs": [],
            "results": None,
            "processed_path": processed_path,
            "report_path": report_path,
            "data_path": data_path,
            "error": None,
        }

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(run_id, data_path, run_similarity),
        daemon=True,
    )
    thread.start()

    return jsonify({"run_id": run_id})


@app.route("/api/status/<run_id>")
def api_status(run_id):
    """Poll the status and log lines of a run."""
    run = _get_run(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    return jsonify({
        "status": run["status"],
        "logs": run["logs"],
        "error": run.get("error"),
    })


@app.route("/api/results/<run_id>")
def api_results(run_id):
    """Return the full analysis results plus list of available charts."""
    run = _get_run(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    if run["status"] != "done":
        return jsonify({"error": "Run is not completed yet"}), 400

    report_path = run["report_path"]
    chart_folder = os.path.join(report_path, "charts")
    charts = []
    if os.path.isdir(chart_folder):
        charts = [f[:-4] for f in os.listdir(chart_folder) if f.endswith(".png")]

    payload = dict(run["results"])
    payload["charts"] = charts

    return jsonify(payload)


@app.route("/api/chart/<run_id>/<chart_name>")
def api_chart(run_id, chart_name):
    """Serve a chart PNG for a given run."""
    run = _get_run(run_id)
    if not run:
        abort(404)

    # Sanitise chart_name to prevent directory traversal
    chart_name = os.path.basename(chart_name)
    chart_path = os.path.join(run["report_path"], "charts", f"{chart_name}.png")

    if not os.path.isfile(chart_path):
        abort(404)

    return send_file(chart_path, mimetype="image/png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting DataLens server on http://localhost:5000")
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
