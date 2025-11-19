import os
from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    send_from_directory,
    abort,
    jsonify,
    flash,
)
from werkzeug.utils import secure_filename
import qrcode
import io
import base64
import secrets


# ---------- Config ----------
UPLOAD_FOLDER = "./data"
ALLOWED_EXT = {".yml", ".yaml", ".txt", ".conf"}
MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB, 可调整
APP_HOST = "0.0.0.0"
APP_PORT = 5000
# ----------------------------

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.secret_key = "replace-with-your-own-secret-if-needed"


# ---------- Helpers ----------
def allowed_filename(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXT


def random_id(length=6):  # 可调长度
    """生成 length 位随机短 ID"""
    return secrets.token_hex((length + 1) // 2)[:length]


def list_files():
    files = []
    for fname in sorted(os.listdir(UPLOAD_FOLDER)):
        path = os.path.join(UPLOAD_FOLDER, fname)
        if os.path.isfile(path):
            size = os.path.getsize(path)
            files.append(
                {
                    "name": fname,
                    "size": size,
                    "raw_url": url_for("raw_file", filename=fname, _external=True),
                    "download_url": url_for(
                        "download_file", filename=fname, _external=True
                    ),
                    "edit_url": url_for("edit_file", filename=fname),
                    "qr_url": url_for("qr_image", filename=fname, _external=True),
                }
            )
    return files


def save_upload(file_storage, filename_override=None):
    filename = secure_filename(file_storage.filename)
    _, ext = os.path.splitext(filename.lower())
    if filename_override:
        # 覆盖编辑时保留原文件名
        filename = filename_override
    else:
        # 新上传，则生成随机短ID文件名
        rid = random_id(6)
        filename = f"{rid}{ext}"
    if not allowed_filename(filename):
        raise ValueError("不支持的文件类型，仅允许: " + ", ".join(ALLOWED_EXT))
    dest = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file_storage.save(dest)
    # log
    app.logger.info(f"Saved file: {dest}")
    return filename


def generate_qr_dataurl(raw_url):
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(raw_url)
    qr.make(fit=True)
    img = qr.make_image()
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    b64 = base64.b64encode(bio.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------- Routes ----------
@app.route("/")
def index():
    files = list_files()
    return render_template("index.html", files=files)


@app.route("/upload", methods=["POST"])
def upload():
    # 单文件上传
    if "file" not in request.files:
        flash("未选择文件", "danger")
        return redirect(url_for("index"))
    f = request.files["file"]
    if f.filename == "":
        flash("未选择文件", "danger")
        return redirect(url_for("index"))
    try:
        name = save_upload(f)
        flash(f"上传成功: {name}", "success")
    except Exception as e:
        app.logger.exception("upload error")
        flash(f"上传失败: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/delete/<filename>", methods=["POST"])
def delete_file(filename):
    safe = secure_filename(filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    if not os.path.exists(file_path):
        flash(f"文件不存在: {safe}", "danger")
        return redirect(url_for("index"))
    try:
        os.remove(file_path)
        flash(f"删除成功: {safe}", "success")
    except Exception as e:
        app.logger.exception("delete error")
        flash(f"删除失败: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/edit/<filename>", methods=["GET", "POST"])
def edit_file(filename):
    safe = secure_filename(filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    if request.method == "GET":
        if not os.path.exists(file_path):
            abort(404)
        raw_url = url_for("raw_file", filename=safe, _external=True)
        qr_data = generate_qr_dataurl(raw_url)
        return render_template(
            "edit.html", filename=safe, raw_url=raw_url, qr_data=qr_data
        )
    # POST -> 覆盖上传
    if "file" not in request.files:
        flash("未选择文件", "danger")
        return redirect(url_for("edit_file", filename=safe))
    f = request.files["file"]
    if f.filename == "":
        flash("未选择文件", "danger")
        return redirect(url_for("edit_file", filename=safe))
    try:
        # 覆盖：强制保存为当前 filename
        save_upload(f, filename_override=safe)
        flash(f"覆盖成功: {safe}", "success")
    except Exception as e:
        app.logger.exception("edit error")
        flash(f"覆盖失败: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/raw/<path:filename>")
def raw_file(filename):
    safe = secure_filename(filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    if not os.path.exists(path):
        abort(404)
    # 返回纯文本（Node配置）
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        safe,
        mimetype="text/plain; charset=utf-8",
        as_attachment=False,
    )


@app.route("/download/<path:filename>")
def download_file(filename):
    safe = secure_filename(filename)
    if not os.path.exists(os.path.join(app.config["UPLOAD_FOLDER"], safe)):
        abort(404)
    return send_from_directory(app.config["UPLOAD_FOLDER"], safe, as_attachment=True)


@app.route("/qr/<path:filename>")
def qr_image(filename):
    safe = secure_filename(filename)
    raw_url = url_for("raw_file", filename=safe, _external=True)
    img_data = generate_qr_dataurl(raw_url)
    # 返回 dataurl 的纯 png
    header, b64 = img_data.split(",", 1)
    return base64.b64decode(b64), 200, {"Content-Type": "image/png"}


# ---------- Routes api ----------


# API列表
@app.route("/api/list")
def api_list():
    return jsonify(list_files())


@app.route("/api/upload", methods=["POST"])
def api_upload():
    # 方便脚本上传（无 token）
    if "file" not in request.files:
        return jsonify({"ok": False, "msg": "no file"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"ok": False, "msg": "empty filename"}), 400
    try:
        name = save_upload(f)
        return jsonify(
            {
                "ok": True,
                "name": name,
                "raw_url": url_for("raw_file", filename=name, _external=True),
            }
        )
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.route("/api/delete/<filename>", methods=["POST"])
def api_delete_file(filename):
    safe = secure_filename(filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    if not os.path.exists(file_path):
        return jsonify({"ok": False, "msg": "file not found"}), 404
    try:
        os.remove(file_path)
        return jsonify({"ok": True, "msg": f"{safe} deleted"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


# ---------- run ----------
if __name__ == "__main__":
    # dev mode
    app.run(host=APP_HOST, port=APP_PORT, debug=True)
