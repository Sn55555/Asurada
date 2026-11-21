#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
core_python="$PWD/.venv/bin/python"
candidate_dir="${ASURADA_CANDIDATE_DIR:-$(mktemp -d /tmp/asurada-candidate-XXXXXX)}"
mkdir -p "$candidate_dir/logs"
candidate_dir="$(cd "$candidate_dir" && pwd -P)"
export ASURADA_RUNTIME_DIR="$candidate_dir/logs"
export ASURADA_SPEECH_SOCKET="$candidate_dir/voice.sock"
export ASURADA_RELATIONSHIP_DB="$candidate_dir/relationship.sqlite3"
export ASURADA_TRAINING_MEMORY_DB="$candidate_dir/training.sqlite3"
export ASURADA_PIT_EVIDENCE_DB="$candidate_dir/pit-evidence.sqlite3"
export ASURADA_ATTACK_MODE_STATE_PATH="$candidate_dir/attack.json"
export ASURADA_DRIVER_ID="${ASURADA_DRIVER_ID:-hayato}"
export ASURADA_PERSONALITY_ENABLED=1
export ASURADA_PERSONALITY_LLM_MODE=disabled
export ASURADA_LLM_SIDECAR_ENABLED=0
port="${ASURADA_CANDIDATE_PORT:-20779}"

if [[ -e "$ASURADA_SPEECH_SOCKET" ]]; then
  printf '%s\n' 'Candidate socket already exists. Use a new candidate directory.' >&2
  exit 1
fi
printf 'Candidate directory: %s\nUDP port: %s\n' "$candidate_dir" "$port"
printf 'Microphone in another terminal, using the same voice configuration:\n'
printf 'ASURADA_RUNTIME_DIR=%q ASURADA_SPEECH_SOCKET=%q ASURADA_TRAINING_MEMORY_DB=%q ASURADA_DRIVER_ID=%q ASURADA_PERSONALITY_ENABLED=1 ASURADA_LLM_SIDECAR_ENABLED=0 %q %q --session-log %q --recognizer-backend macos_speech --race-dialogue --manual --disable-wake-word --show-processing-json\n' \
  "$ASURADA_RUNTIME_DIR" "$ASURADA_SPEECH_SOCKET" "$ASURADA_TRAINING_MEMORY_DB" "$ASURADA_DRIVER_ID" \
  "$core_python" "$PWD/scripts/phase3_macos_voice_loop.py" "$ASURADA_RUNTIME_DIR/session_log.jsonl"
"$core_python" -m asurada.speech_service --socket "$ASURADA_SPEECH_SOCKET" \
  --session-source "$ASURADA_RUNTIME_DIR/latest_snapshot.json" >"$candidate_dir/speech.log" 2>&1 &
speech_pid=$!
trap 'kill -TERM "$speech_pid" 2>/dev/null || true; wait "$speech_pid" 2>/dev/null || true' EXIT
for ((attempt=0; attempt<40; attempt++)); do
  [[ -S "$ASURADA_SPEECH_SOCKET" ]] && break
  kill -0 "$speech_pid" 2>/dev/null || break
  sleep .1
done
[[ -S "$ASURADA_SPEECH_SOCKET" ]] || { cat "$candidate_dir/speech.log" >&2; exit 1; }
"$core_python" -m asurada --live-udp --udp-port "$port" --record-capture-jsonl "$candidate_dir/capture.jsonl"
