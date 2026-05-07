#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

import artemis_v3_1 as artemis


HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _binary_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    content_type: str,
    filename: str,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _configure_artemis(options: Dict[str, Any]) -> str:
    mode = options.get("mode") if options.get("mode") in artemis.MODE_CONFIG else "balanced"
    llm_mode = options.get("llmMode") if options.get("llmMode") in {"full", "judge", "off"} else "full"

    artemis.apply_mode(mode)
    artemis.CONFIG["llm_mode"] = llm_mode
    artemis.CONFIG["allow_empty_target"] = bool(options.get("allowEmptyTarget", False))
    artemis.CONFIG["include_named_entities"] = bool(options.get("includeNamedEntities", False))
    artemis.CONFIG["require_target_substring"] = bool(options.get("requireTargetSubstring", False))
    artemis.CONFIG["debug_candidates"] = False

    if artemis.CONFIG["llm_mode"] != "off" and not artemis.CONFIG["api_key"]:
        artemis.CONFIG["llm_mode"] = "off"

    return artemis.CONFIG["llm_mode"]


class ArtemisHandler(BaseHTTPRequestHandler):
    server_version = "ArtemisAPI/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[API] {self.address_string()} - {fmt % args}")

    def do_OPTIONS(self) -> None:
        _json_response(self, 200, {"ok": True})

    def do_GET(self) -> None:
        if self.path == "/api/health":
            _json_response(self, 200, {"ok": True, "service": "artemis-python"})
            return
        _json_response(self, 404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        if self.path == "/api/extract":
            self._handle_extract()
            return
        if self.path == "/api/export-xlsx":
            self._handle_export_xlsx()
            return
        _json_response(self, 404, {"ok": False, "error": "Not found"})

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _handle_extract(self) -> None:
        try:
            request = self._read_json_body()
            payload = request.get("payload")
            if payload is None:
                raise ValueError("Missing payload")

            effective_llm_mode = _configure_artemis(request)

            with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as tmp:
                json.dump(payload, tmp, ensure_ascii=False)
                tmp_path = tmp.name

            try:
                pairs = artemis.read_json_pairs(tmp_path)
                rows = artemis.extract_terms(pairs, tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "rows": rows,
                    "totalPairs": len(pairs),
                    "effectiveLlmMode": effective_llm_mode,
                },
            )
        except Exception as exc:
            _json_response(self, 500, {"ok": False, "error": str(exc)})

    def _handle_export_xlsx(self) -> None:
        try:
            request = self._read_json_body()
            rows = request.get("rows")
            if not isinstance(rows, list):
                raise ValueError("Missing rows")

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                output_path = tmp.name

            try:
                artemis.export_excel(rows, output_path)
                body = Path(output_path).read_bytes()
            finally:
                Path(output_path).unlink(missing_ok=True)

            _binary_response(
                self,
                200,
                body,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "artemis_terms.xlsx",
            )
        except Exception as exc:
            _json_response(self, 500, {"ok": False, "error": str(exc)})
            return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), ArtemisHandler)
    print(f"ARTEMIS Python API listening on http://{HOST}:{PORT}")
    print("Use Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
