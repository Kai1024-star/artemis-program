#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List


ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def clean_process_output(value: str) -> str:
    return ANSI_PATTERN.sub("", value).replace("\r", "").strip()


def to_srt_time(seconds: str) -> str:
    value = float(seconds)
    td = timedelta(seconds=value)
    total_seconds = int(td.total_seconds())
    millis = int(round((value - total_seconds) * 1000))

    if millis == 1000:
        total_seconds += 1
        millis = 0

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def json_fragments_to_srt(fragments: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for idx, frag in enumerate(fragments, start=1):
        start = to_srt_time(frag["begin"])
        end = to_srt_time(frag["end"])
        text = "\n".join(frag.get("lines", []))
        blocks.append(f"{idx}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks)


def convert_aeneas_json_to_srt(json_path: Path, srt_path: Path) -> None:
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    srt_path.write_text(json_fragments_to_srt(data["fragments"]), encoding="utf-8")


def run_aeneas_alignment(
    text_path: Path,
    audio_path: Path,
    output_json_path: Path,
    log_path: Path,
    *,
    language: str = "Mizuki",
    voice_id: str = "Mizuki",
) -> None:
    command = [
        sys.executable,
        "-m",
        "aeneas.tools.execute_task",
        str(audio_path),
        str(text_path),
        f"task_language={language}|is_text_type=plain|os_task_file_format=json",
        f"-r=tts=aws|allow_unlisted_languages=True|voiceId={voice_id}",
        f"-l={log_path}",
        str(output_json_path),
    ]
    env = os.environ.copy()
    aws_region = env.get("AWS_DEFAULT_REGION") or env.get("AWS_REGION") or "ap-northeast-1"
    env["AWS_DEFAULT_REGION"] = aws_region
    env["AWS_REGION"] = aws_region

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        details = clean_process_output(result.stderr or result.stdout or "aeneas alignment failed")
        if log_path.exists():
            log_tail = clean_process_output(log_path.read_text(encoding="utf-8", errors="replace")[-4000:])
            if log_tail:
                details = f"{details}\n\n--- aeneas log ---\n{log_tail}"
        raise RuntimeError(details[-2000:])


def align_text_audio_to_srt(
    text_path: Path,
    audio_path: Path,
    output_dir: Path,
    output_name: str,
    *,
    language: str = "Mizuki",
    voice_id: str = "Mizuki",
) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in output_name).strip("_")
    if not safe_name:
        safe_name = "artemis_alignment"

    output_json_path = output_dir / f"{safe_name}.json"
    output_srt_path = output_dir / f"{safe_name}.srt"
    log_path = output_dir / f"{safe_name}.log"

    run_aeneas_alignment(
        text_path=text_path,
        audio_path=audio_path,
        output_json_path=output_json_path,
        log_path=log_path,
        language=language,
        voice_id=voice_id,
    )
    convert_aeneas_json_to_srt(output_json_path, output_srt_path)

    return {
        "json": output_json_path,
        "srt": output_srt_path,
        "log": log_path,
    }
