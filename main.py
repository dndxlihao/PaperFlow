import os
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from getDoc import (
    crawl_issue_by_pages,
    down_pdf,
    pdf_ocr,
)

app = Flask(__name__)
CORS(app)

@app.route("/api/ieee", methods=["GET"])
def get_ieee():
    punumber = request.args.get("punumber")
    isnumber = request.args.get("isnumber")
    if not punumber or not isnumber:
        return jsonify({"error": "Missing required parameters: punumber, isnumber"}), 400

    length = 25
    if "len" in request.args:
        try:
            length = int(request.args.get("len"))
        except ValueError:
            return jsonify({"error": "Invalid parameter: len must be an integer"}), 400

    sortType = request.args.get("sortType") or "paper-citations"

    try:
        start_page = int(request.args.get("start_page", 1))
        end_page = int(request.args.get("end_page", start_page))
    except ValueError:
        return jsonify({"error": "Invalid parameter: start_page/end_page must be integers"}), 400

    if start_page < 1 or end_page < 1 or end_page < start_page:
        return jsonify({"error": "Invalid page range: require 1 <= start_page <= end_page"}), 400

    try:
        items = crawl_issue_by_pages(
            punumber=punumber,
            isnumber=isnumber,
            start_page=start_page,
            end_page=end_page,
            rows_per_page=length,
            sortType=sortType,
            download_pdf=True,  
            attach_text=True,
        )
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/pdf", methods=["GET"])
def get_pdf():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing required parameter: code"}), 400

    try:
        down_pdf(code)

        file_path = f"docs/{code}.pdf"
        if not os.path.exists(file_path):
            return "The requested PDF file was not found.", 404

        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/content", methods=["GET"])
def get_content():
    code = request.args.get("code")
    if not code:
        return jsonify({"error": "Missing required parameter: code"}), 400

    try:
        pdf_path = f"docs/{code}.pdf"
        if not os.path.exists(pdf_path):
            down_pdf(code)

        text = pdf_ocr(code)
        return jsonify({"code": code, "content": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
