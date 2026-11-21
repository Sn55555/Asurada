"""Measure local/tunneled Ollama quality and the independent S6 runtime deadline."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import http.client
from itertools import product
import json
from pathlib import Path
import random
import subprocess
import time
from urllib.parse import urlsplit

from asurada.cancellable_http import request_json
from asurada.personality_dialogue import EVENT_LINES
from asurada.personality_llm import OllamaProvider, PersonalityLlm, validate_fragment
from asurada.task_runtime import TaskContext
from personality_model_regression import OPPORTUNITIES, TONES, await_result, request_for


def metadata(provider):
    base = provider.url.removesuffix("/api/generate")
    tags = request_json(base + "/api/tags", method="GET", body=None, context=TaskContext.start("model-tags", 3000),
                        timeout_ms=3000, max_response_bytes=131072, propagate_budget=False)
    entry = next((row for row in tags["models"] if provider.model in (row.get("name"), row.get("model"))), None)
    if entry is None:
        raise ValueError(f"Model {provider.model} is absent from this Ollama endpoint")
    show = request_json(base + "/api/show", method="POST", context=TaskContext.start("model-show", 3000),
                        timeout_ms=3000, max_response_bytes=1048576, propagate_budget=False,
                        body={"model": provider.model})
    license_text = show.get("license", "")
    return {"tag": provider.model, "digest": entry.get("digest"), "details": entry.get("details"),
            "license_first_line": next((line.strip() for line in license_text.splitlines() if line.strip()), None),
            "license_sha256": sha256(license_text.encode()).hexdigest() if license_text else None}


def observe_stream(provider, request, *, timeout):
    # Only actual streamed response tokens count toward TTFT. This stream is an
    # isolated benchmark, while timed runtime samples use the production client.
    body = provider.request_body(request)
    wire_ref = body["format"]["properties"]["decision_ref"]["enum"][0]
    body["stream"] = True
    target = urlsplit(provider.url)
    connection_type = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(target.hostname, target.port, timeout=timeout)
    started = time.monotonic()
    first_token_ms = None
    chunks = []
    size = 0
    try:
        connection.request("POST", target.path, body=json.dumps(body).encode(),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return {"status": "http_error", "http_status": response.status}
        while time.monotonic() - started < timeout:
            line = response.readline(16385)
            if not line:
                break
            size += len(line)
            if size > 65536:
                return {"status": "oversize_stream"}
            piece = json.loads(line)
            if not isinstance(piece, dict):
                return {"status": "invalid_stream", "ttft_ms": first_token_ms}
            token = piece.get("response")
            if isinstance(token, str) and token:
                if first_token_ms is None:
                    first_token_ms = (time.monotonic() - started) * 1000
                chunks.append(token)
            if piece.get("done") is True:
                break
        else:
            return {"status": "timeout", "ttft_ms": first_token_ms}
        if not line or piece.get("done") is not True:
            return {"status": "incomplete_stream", "ttft_ms": first_token_ms}
        elapsed_ms = (time.monotonic() - started) * 1000
        raw = "".join(chunks)
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        fragment = None
        if isinstance(payload, dict) and payload.get("decision_ref") == wire_ref:
            fragment = validate_fragment({**payload, "decision_ref": request.decision_ref}, request)
        elapsed_ns, count = piece.get("eval_duration"), piece.get("eval_count")
        return {"status": "ok" if fragment else "invalid", "fragment": fragment, "raw": raw,
                "ttft_ms": first_token_ms, "elapsed_ms": elapsed_ms,
                "model_load_ms": (piece.get("load_duration") or 0) / 1_000_000,
                "tokens_per_s": count * 1_000_000_000 / elapsed_ns if count and elapsed_ns else None}
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return {"status": "timeout" if isinstance(exc, TimeoutError) else "stream_error", "error": type(exc).__name__,
                "ttft_ms": first_token_ms}
    finally:
        connection.close()


def percentile_metrics(values):
    numbers = sorted(x for x in values if x is not None)
    return {f"p{rate}": round(numbers[round((len(numbers) - 1) * rate / 100)], 2) if numbers else None
            for rate in (50, 95, 99)}


def evaluate(provider, *, repeats, timeout):
    model = metadata(provider)
    rows = []
    worker = PersonalityLlm(mode="shadow", provider=provider)
    try:
        for stage, opportunity in product(range(4), OPPORTUNITIES):
            request = request_for("synthetic-race", stage, opportunity, TONES[stage])
            template = EVENT_LINES[opportunity][stage][0]
            for repeat in range(1, repeats + 1):
                stream = observe_stream(provider, request, timeout=timeout)
                runtime = await_result(worker) if worker.start(request) else None
                rows.append({"request": asdict(request), "repeat": repeat, "template": template,
                             "stream": stream, "production_shadow": asdict(runtime) if runtime else None})
    finally:
        worker.close()
    stream_status = Counter(row["stream"]["status"] for row in rows)
    runtime_status = Counter(row["production_shadow"]["status"] if row["production_shadow"] else "missing" for row in rows)
    options = provider.request_body(request)["options"]
    return {"model": model, "ollama_options": options, "stream_status": dict(stream_status),
            "worker_deadline_status": dict(runtime_status),
            "stream_ttft_ms": percentile_metrics(row["stream"].get("ttft_ms") for row in rows),
            "stream_completion_ms": percentile_metrics(row["stream"].get("elapsed_ms") for row in rows),
            "worker_deadline_completion_ms": percentile_metrics(row["production_shadow"]["elapsed_ms"]
                                                                  for row in rows if row["production_shadow"]),
            "rows": rows}


def blind_evaluation(models, seed):
    groups = {}
    for model in models:
        for row in model.get("rows", []):
            request, stream = row["request"], row["stream"]
            group = groups.setdefault((request["request_id"], row["repeat"]), {
                "opportunity": request["opportunity"], "stage": request["stage"], "tone": request["tone"],
                "variants": [("template", row["template"])],
            })
            if stream["status"] == "ok":
                group["variants"].append((model["model"]["tag"], stream["fragment"] + " " + row["template"]))
    generator = random.Random(seed)
    forms, key = [], {}
    for index, group in enumerate(groups.values(), start=1):
        choices = group.pop("variants")
        if len(choices) < 2:
            continue
        generator.shuffle(choices)
        labels = [f"{index:03d}-{suffix}" for suffix in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[:len(choices)]]
        key.update(zip(labels, (source for source, _ in choices)))
        forms.append({**group, "samples": [{"id": label, "text": text} for label, (_, text) in zip(labels, choices)]})
    return forms, key


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_baseline():
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=False, capture_output=True, text=True)
    relevant = (Path(__file__).resolve(), repo / "asurada-core/src/asurada/personality_llm.py",
                repo / "asurada-core/src/asurada/personality_dialogue.py", repo / "asurada-core/src/asurada/output.py")
    return {"commit": result.stdout.strip() if result.returncode == 0 else None,
            "working_source_sha256": {str(path.relative_to(repo)): sha256(path.read_bytes()).hexdigest() for path in relevant}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", action="append", required=True, help="Exact local model tag. Repeat for A/B.")
    parser.add_argument("--seed", default=42, type=int)
    parser.add_argument("--repeats", default=1, type=int)
    parser.add_argument("--sample-timeout", default=10., type=float, help="Offline streaming timeout in seconds.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or not 0 < args.sample_timeout <= 120 or len(args.model) > 25:
        parser.error("Use positive repeats, at most 25 models and a streaming timeout within 120 seconds")
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for model in dict.fromkeys(args.model):
        try:
            results.append(evaluate(OllamaProvider(args.base_url, model, seed=args.seed), repeats=args.repeats,
                                    timeout=args.sample_timeout))
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            results.append({"model": {"tag": model}, "error": str(exc)})
    forms, answer_key = blind_evaluation(results, args.seed)
    save(args.output / "ollama-benchmark.json", {"mode": "offline_stream_and_worker_deadline", "seed": args.seed,
         "repeats": args.repeats, "worker_deadline_ms": 600, "models": results, "source": source_baseline(),
         "scope": "Synthetic prompts across H0–H3, no audio; the production speech owner independently gates model use to H2–H3."})
    save(args.output / "blind-review.json", {"dimensions": ["自然度", "中文流畅度", "角色一致性", "幽默得体",
                                                               "事实准确性", "简洁程度"], "groups": forms})
    save(args.output / "blind-answer-key.json", answer_key)
    print(json.dumps([{key: value for key, value in model.items() if key != "rows"} for model in results], ensure_ascii=False))
    return 0 if all(model.get("stream_status", {}).get("ok", 0) > 0 for model in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
