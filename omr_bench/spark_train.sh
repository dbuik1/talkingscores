#!/usr/bin/env bash
# Train our own copy of homr's transcription model on the Spark, then add it
# to the bench as the reader "homr-spark" so it is scored against stock homr.
#
# Run on: the DGX Spark, as David's own user (the one with sudo), in bash,
#         after spark_bench.sh has installed the bench.
# Usage:  spark_train.sh          set up, build the training pages and start training in the background
#         spark_train.sh status   show how far training has got
#         spark_train.sh stop     stop training; the next start carries on from the last saved epoch
#         spark_train.sh export   turn the trained model into a reader and add it to the bench
# Changes: everything lives in ~/omr/homr-train (about 60 GB with the training
#          pages): homr's source at a fixed commit, its Python environment,
#          MuseScore for drawing pages, and the downloaded scores. Installs
#          rsvg-convert, FUSE 2, JACK, libvips and libmagic with apt. Adds a
#          [engines.homr-spark] section to omr_bench/engines.toml on export.
#          Undo: rm -rf ~/omr/homr-train and delete that section.
# homr publishes only its finished ONNX models, not the PyTorch weights, so
# this trains from scratch on the same open scores homr uses: OpenScore Lieder
# and String Quartets, GrandStaff, Camera-PrIMuS, PDMX and MuseTrainer.
# Training runs at low priority under a memory cap so CI and the local models
# keep their room, and takes days. Safe to run again: finished steps are
# reported and skipped, and a stopped run resumes from its last epoch.

set -euo pipefail

MODE="${1:-start}"
OMR="$HOME/omr"
REPO="$OMR/talkingscores"
TRAIN="$OMR/homr-train"
SRC="$TRAIN/homr"
VENV="$TRAIN/venv"
LOG="$TRAIN/train.log"
PIDFILE="$TRAIN/train.pid"
HOMR_URL="https://github.com/liebharc/homr"
# The commit whose training scripts this was written against; a newer homr can
# rename the dataset converters or the model file names this script relies on.
HOMR_COMMIT="2d7e8c3b500ab9af10e579bebab8c0d9e551eb71"
MUSESCORE_URL="https://github.com/musescore/MuseScore/releases/download/v4.6.5/MuseScore-Studio-4.6.5.253511702-aarch64.AppImage"
TORCH_INDEX="https://download.pytorch.org/whl/cu130"
TRAIN_MEMORY="${TRAIN_MEMORY:-48G}"
MIN_FREE_GB=80

DONE=(); ALREADY=(); FAILED=(); DIED=
done_() { DONE+=("$1"); echo "done: $1"; }
already() { ALREADY+=("$1"); echo "already: $1"; }
failed() { FAILED+=("$1"); echo "FAILED: $1" >&2; }
die() { DIED=1; echo "Stopped: $1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

summary() {
  local status=$?
  [ "$status" -eq 0 ] || [ -n "$DIED" ] || [ ${#FAILED[@]} -gt 0 ] || failed "the script stopped early (exit code $status) after the last line above"
  [ ${#DONE[@]} -gt 0 ] || [ ${#ALREADY[@]} -gt 0 ] || [ ${#FAILED[@]} -gt 0 ] || return 0
  echo
  echo "Summary"
  for line in "${DONE[@]+"${DONE[@]}"}"; do echo "  changed: $line"; done
  for line in "${ALREADY[@]+"${ALREADY[@]}"}"; do echo "  already fine: $line"; done
  for line in "${FAILED[@]+"${FAILED[@]}"}"; do echo "  failed: $line"; done
  [ ${#FAILED[@]} -eq 0 ] || echo "  Send this summary back to Claude to fix the failed steps."
}
trap summary EXIT

running_pid() {
  [ -f "$PIDFILE" ] || return 1
  local pid
  pid=$(cat "$PIDFILE")
  kill -0 "$pid" 2>/dev/null && echo "$pid"
}

latest_checkpoint() {
  # Trainer saves one folder per epoch as current_training/checkpoint-<step>.
  # Before the first epoch the folder doesn't exist, which must mean "none", not an error.
  [ -d "$SRC/current_training" ] || return 0
  find "$SRC/current_training" -maxdepth 1 -type d -name 'checkpoint-*' 2>/dev/null \
    | sed -E 's#.*/checkpoint-##' | sort -n | tail -1 | sed -E 's#^#checkpoint-#'
}

trained_model() {
  [ -d "$SRC/training/architecture/transformer" ] || return 0
  find "$SRC/training/architecture/transformer" -maxdepth 1 -name 'pytorch_model_*.pth' -newer "$SRC/pyproject.toml" \
    -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-
}

# --- preconditions -----------------------------------------------------------
[ "$(uname -m)" = aarch64 ] || die "this is for the DGX Spark (aarch64); this machine is $(uname -m)."
have git || die "git isn't installed. Run: sudo apt-get install -y git"
have curl || die "curl isn't installed. Run: sudo apt-get install -y curl"
[ -d "$REPO/.git" ] || die "the bench isn't installed. Run spark_bench.sh first."

# A clone left at an older commit would run the old steps, so update it and
# restart on the new copy before doing anything else.
if [ -z "${OMR_SCRIPT_UPDATED:-}" ] && [ -d "$REPO/.git" ]; then
  before=$(git -C "$REPO" rev-parse HEAD)
  if git -C "$REPO" pull -q --ff-only; then
    if [ "$(git -C "$REPO" rev-parse HEAD)" != "$before" ]; then
      echo "updated talkingscores to $(git -C "$REPO" rev-parse --short HEAD); restarting with the new script"
      OMR_SCRIPT_UPDATED=1 exec bash "$REPO/omr_bench/spark_train.sh" "$@"
    fi
  else
    echo "couldn't update $REPO with git pull; carrying on with the copy on disk" >&2
  fi
fi
mkdir -p "$TRAIN"

# --- setup -------------------------------------------------------------------
apt_first_of() {
  # Ubuntu 24.04 renamed some libraries with a t64 suffix; use whichever name exists.
  local name
  for name in "$@"; do
    dpkg -s "$name" >/dev/null 2>&1 && return 0
  done
  for name in "$@"; do
    apt-cache show "$name" >/dev/null 2>&1 && { echo "$name"; return 0; }
  done
  return 1
}

setup_system() {
  local missing=() pkg
  for choice in "librsvg2-bin" "libfuse2t64 libfuse2" "libjack-jackd2-0" "libvips42t64 libvips42" "libmagic1t64 libmagic1"; do
    # shellcheck disable=SC2086
    pkg=$(apt_first_of $choice) || { failed "no package found for: $choice"; continue; }
    [ -n "$pkg" ] && missing+=("$pkg")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    sudo apt-get install -y -qq "${missing[@]}" >/dev/null && done_ "installed ${missing[*]}"
  else
    already "rsvg-convert, FUSE 2, JACK, libvips and libmagic installed"
  fi
}

setup_source() {
  if [ -d "$SRC/.git" ] && [ "$(git -C "$SRC" rev-parse HEAD)" = "$HOMR_COMMIT" ]; then
    already "homr source at ${HOMR_COMMIT:0:7} in $SRC"
    return
  fi
  if [ ! -d "$SRC/.git" ]; then
    git init -q "$SRC"
    git -C "$SRC" remote add origin "$HOMR_URL"
  fi
  git -C "$SRC" fetch -q --depth 1 origin "$HOMR_COMMIT"
  git -C "$SRC" checkout -q --force FETCH_HEAD
  done_ "checked out homr ${HOMR_COMMIT:0:7} in $SRC"
}

setup_python() {
  if "$VENV/bin/python" -c 'import torch, transformers, homr; assert torch.cuda.is_available()' 2>/dev/null; then
    already "training environment in $VENV"
    return
  fi
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  # homr's dev group pins onnx-simplifier, which has no aarch64 build under that
  # name; the same tool ships aarch64 wheels as onnxsim, so it is swapped in.
  local reqs="$TRAIN/requirements.txt"
  "$VENV/bin/python" - "$SRC/pyproject.toml" >"$reqs" <<'PY'
import sys, tomllib
project = tomllib.load(open(sys.argv[1], "rb"))
for req in project["dependency-groups"]["dev"]:
    if not req.replace("_", "-").startswith("onnx-simplifier"):
        print(req)
print("onnxsim >= 0.6.5, < 0.9")
PY
  if "$VENV/bin/pip" install -q torch torchvision --index-url "$TORCH_INDEX" && \
     (cd "$SRC" && "$VENV/bin/pip" install -q -e ".[cpu]" -r "$reqs"); then
    # A dependency can swap the CUDA build of torch for a CPU one; put the CUDA one back.
    if ! "$VENV/bin/python" -c 'import torch; assert torch.cuda.is_available()' 2>/dev/null; then
      "$VENV/bin/pip" install -q --force-reinstall --no-deps torch torchvision --index-url "$TORCH_INDEX"
    fi
    if "$VENV/bin/python" -c 'import torch, transformers, homr; assert torch.cuda.is_available()' 2>/dev/null; then
      done_ "made the training environment in $VENV"
    else
      failed "the training environment installed but torch can't see the GPU; run: $VENV/bin/python -c 'import torch; print(torch.cuda.is_available())'"
    fi
  else
    failed "the training environment didn't install; the pip error is above"
  fi
}

setup_musescore() {
  # homr's own converter downloads the x86 MuseScore, which can't run here; a file already in place is used as it is.
  local target="$SRC/datasets/MuseScore"
  if [ -x "$target" ]; then
    already "MuseScore for aarch64 in $target"
    return
  fi
  mkdir -p "$SRC/datasets"
  if curl -fsSL -o "$target.part" "$MUSESCORE_URL"; then
    mv "$target.part" "$target"
    chmod 755 "$target"
    done_ "downloaded MuseScore 4.6.5 for aarch64"
  else
    rm -f "$target.part"
    failed "MuseScore didn't download from $MUSESCORE_URL"
  fi
}

# --- training ----------------------------------------------------------------
start_training() {
  local pid
  if pid=$(running_pid); then
    already "training is running (process $pid); see progress with: $0 status"
    return
  fi
  if [ -n "$(trained_model)" ]; then
    already "a trained model exists: $(trained_model). Add it to the bench with: $0 export"
    return
  fi
  local free_gb
  free_gb=$(df -BG --output=avail "$TRAIN" | tail -1 | tr -dc 0-9)
  [ "$free_gb" -ge "$MIN_FREE_GB" ] || { failed "only ${free_gb} GB free in $TRAIN; ${MIN_FREE_GB} GB is needed for the training pages"; return; }

  local resume
  resume=$(latest_checkpoint)
  # train_transformer deletes current_training unless told which checkpoint to resume from.
  local call="from training.transformer.train import train_transformer; train_transformer(resume='$resume')"
  local cap=()
  if have systemd-run && systemd-run --user --scope -q -p MemoryMax="$TRAIN_MEMORY" true 2>/dev/null; then
    cap=(systemd-run --user --scope -q -p MemoryMax="$TRAIN_MEMORY")
  fi
  (
    cd "$SRC"
    # MuseScore draws the pages with no screen attached, and runs without mounting its AppImage.
    export PYTHONPATH="$SRC" PATH="$VENV/bin:$PATH" GIT_TERMINAL_PROMPT=0 \
      QT_QPA_PLATFORM=offscreen APPIMAGE_EXTRACT_AND_RUN=1
    setsid nohup "${cap[@]}" nice -n 10 "$VENV/bin/python" -c "$call" </dev/null >>"$LOG" 2>&1 &
    echo $! >"$PIDFILE"
  )
  sleep 5
  if pid=$(running_pid); then
    if [ -n "$resume" ]; then
      done_ "training resumed from $resume (process $pid)"
    else
      done_ "training started (process $pid). The first hours build the training pages; then it trains for days"
    fi
    echo "Progress: $0 status    Log: $LOG"
  else
    failed "training stopped straight away; the end of $LOG says why"
    tail -20 "$LOG" >&2 || true
  fi
}

show_status() {
  local pid
  if pid=$(running_pid); then
    echo "Training is running (process $pid)."
  elif [ -n "$(trained_model)" ]; then
    echo "Training finished: $(trained_model)"
    echo "Add it to the bench with: $0 export"
  else
    echo "Training isn't running."
    [ -n "$(latest_checkpoint)" ] && echo "Last saved: $(latest_checkpoint). Carry on with: $0"
  fi
  [ -f "$LOG" ] || return 0
  echo
  echo "Latest scores (eval_accuracy rises towards 1):"
  grep -oE "\{'eval_loss'[^}]*\}" "$LOG" | tail -3 || echo "  none yet; the first comes after one epoch"
  echo
  echo "Last log line:"
  tr '\r' '\n' <"$LOG" | grep -v '^\s*$' | tail -1
  have nvidia-smi && { echo; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader | sed 's/^/GPU busy, memory: /'; }
}

stop_training() {
  local pid
  if pid=$(running_pid); then
    # TERM, not Ctrl+C: on Ctrl+C homr saves the half-trained model as if training had finished.
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
    done_ "stopped training. Carry on from the last saved epoch with: $0"
  else
    already "training wasn't running"
  fi
}

# --- export ------------------------------------------------------------------
export_model() {
  local model name
  model=$(trained_model)
  [ -n "$model" ] || die "no trained model yet. See: $0 status"
  name=$(basename "$model" .pth)
  # homr's ONNX converter and reader both find the model through this one name.
  sed -i -E "s/model_name = \"pytorch_model_[^\"]*\"/model_name = \"$name\"/" "$SRC/homr/transformer/configs.py"
  grep -q "model_name = \"$name\"" "$SRC/homr/transformer/configs.py" || die "couldn't point homr at $name in homr/transformer/configs.py"
  if ls "$SRC"/homr/transformer/encoder_"$name"*.onnx >/dev/null 2>&1; then
    already "ONNX models for $name"
  elif (cd "$SRC" && PYTHONPATH="$SRC" "$VENV/bin/python" training/onnx/main.py --tromr); then
    done_ "converted $name to ONNX"
  else
    failed "ONNX conversion failed; the error is above"
    return
  fi

  local engines="$REPO/omr_bench/engines.toml"
  if grep -q '^\[engines\.homr-spark\]' "$engines"; then
    already "homr-spark is in omr_bench/engines.toml"
  else
    cat >>"$engines" <<EOF

[engines.homr-spark]
# homr with the transcription model trained on the Spark by spark_train.sh.
command = ["$VENV/bin/homr", "{image}"]
output = "*.musicxml"
EOF
    done_ "added homr-spark to omr_bench/engines.toml"
  fi
  echo "Score it against the other readers with: bash $REPO/omr_bench/spark_bench.sh run"
}

case "$MODE" in
  start)
    setup_system
    setup_source
    setup_python
    setup_musescore
    [ ${#FAILED[@]} -eq 0 ] || die "setup failed, so training wasn't started."
    start_training
    ;;
  status) show_status ;;
  stop) stop_training ;;
  export) export_model ;;
  *) die "unknown mode '$MODE'. Use no argument to start, or: status, stop, export" ;;
esac
