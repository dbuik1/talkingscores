#!/usr/bin/env bash
# Train our own copy of Transcoda on the Spark, starting from its released
# weights, then add it to the bench as the reader "transcoda-spark" so it is
# scored against the released model and the other readers.
#
# Run on: the DGX Spark, as David's own user (the one with sudo), in bash,
#         after spark_bench.sh has installed the bench and Transcoda.
# Usage:  spark_transcoda.sh          set up, then build the training pages and train in the background
#         spark_transcoda.sh status   show how far page building or training has got
#         spark_transcoda.sh stop     stop; the next start carries on from the last saved checkpoint
#         spark_transcoda.sh export   add the trained model to the bench as transcoda-spark
# Changes: everything lives in ~/omr/transcoda-train (about 40 GB with the
#          training pages): Transcoda's source at a fixed commit with
#          transcoda-init-from.patch, its Python environment, humlib's
#          musicxml2hum, OpenScore Lieder and String Quartets, and GrandStaff.
#          Installs GNU parallel, make, g++ and libvips with apt. Adds an
#          [engines.transcoda-spark] section to omr_bench/engines.toml on export.
#          Undo: rm -rf ~/omr/transcoda-train and delete that section.
# Transcoda's training started from an image encoder that was never published,
# so this keeps training the released model on freshly drawn pages instead of
# starting from scratch. Page building and training run at low priority under
# a memory cap so CI and the local models keep their room. Safe to run again:
# finished steps are reported and skipped.

set -euo pipefail

MODE="${1:-start}"
OMR="$HOME/omr"
REPO="$OMR/talkingscores"
TRAIN="$OMR/transcoda-train"
SRC="$TRAIN/transcoda"
SOURCES="$TRAIN/sources"
INTERIM="$TRAIN/data/interim/train"
PAGES="$TRAIN/data/pages"
RUN="$TRAIN/run"
LOG="$TRAIN/train.log"
PIDFILE="$TRAIN/train.pid"
LASTRUN="$TRAIN/last-run.txt"
RELEASED="$OMR/transcoda/weights/model.ckpt"
TRANSCODA_URL="https://github.com/btrkeks/transcoda"
# The commit the patch and the data steps were written against; a newer
# Transcoda can rename the pipeline modules or train.py's options.
TRANSCODA_COMMIT="d4e2e687d5679ae96ca4aa6f01e06a5b338cd488"
PATCH="$REPO/omr_bench/transcoda-init-from.patch"
MUSESCORE_URL="https://github.com/musescore/MuseScore/releases/download/v4.6.5/MuseScore-Studio-4.6.5.253511702-aarch64.AppImage"
TORCH_INDEX="https://download.pytorch.org/whl/cu130"
TRAIN_PAGES="${TRAIN_PAGES:-60000}"
CHECK_PAGES="${CHECK_PAGES:-500}"
MAX_TOKENS=2048
TRAIN_MEMORY="${TRAIN_MEMORY:-48G}"
MIN_FREE_GB=60

DONE=(); ALREADY=(); FAILED=(); DIED=
done_() { DONE+=("$1"); echo "done: $1"; }
already() { ALREADY+=("$1"); echo "already: $1"; }
failed() { FAILED+=("$1"); echo "FAILED: $1" >&2; }
die() { DIED=1; echo "Stopped: $1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
say() { echo "$(date '+%Y-%m-%d %H:%M') $1"; }

summary() {
  local status=$?
  [ "$MODE" = _job ] && return 0
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

best_checkpoint() {
  [ -d "$RUN" ] || return 0
  find "$RUN" -maxdepth 1 -name 'transcoda-spark*.ckpt' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-
}

# --- preconditions -----------------------------------------------------------
if [ "$MODE" != _job ]; then
  [ "$(uname -m)" = aarch64 ] || die "this is for the DGX Spark (aarch64); this machine is $(uname -m)."
  have git || die "git isn't installed. Run: sudo apt-get install -y git"
  have curl || die "curl isn't installed. Run: sudo apt-get install -y curl"
  [ -d "$REPO/.git" ] || die "the bench isn't installed. Run spark_bench.sh first."
  [ -s "$RELEASED" ] || die "Transcoda's released weights aren't in $RELEASED. Run spark_bench.sh first."

  # A clone left at an older commit would run the old steps, so update it and
  # restart on the new copy before doing anything else.
  if [ -z "${OMR_SCRIPT_UPDATED:-}" ]; then
    before=$(git -C "$REPO" rev-parse HEAD)
    if git -C "$REPO" pull -q --ff-only; then
      if [ "$(git -C "$REPO" rev-parse HEAD)" != "$before" ]; then
        echo "updated talkingscores to $(git -C "$REPO" rev-parse --short HEAD); restarting with the new script"
        OMR_SCRIPT_UPDATED=1 exec bash "$REPO/omr_bench/spark_transcoda.sh" "$@"
      fi
    else
      echo "couldn't update $REPO with git pull; carrying on with the copy on disk" >&2
    fi
  fi
  mkdir -p "$TRAIN"
fi
export PATH="$HOME/.local/bin:$TRAIN/humlib/bin:$PATH"

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
  local missing=() pkg choice
  for choice in "parallel" "make" "g++" "libvips42t64 libvips42"; do
    # shellcheck disable=SC2086
    pkg=$(apt_first_of $choice) || { failed "no package found for: $choice"; continue; }
    [ -n "$pkg" ] && missing+=("$pkg")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    sudo apt-get install -y -qq "${missing[@]}" >/dev/null && done_ "installed ${missing[*]}"
  else
    already "GNU parallel, make, g++ and libvips installed"
  fi
}

setup_source() {
  if [ ! -d "$SRC/.git" ] || [ "$(git -C "$SRC" rev-parse HEAD)" != "$TRANSCODA_COMMIT" ]; then
    if [ ! -d "$SRC/.git" ]; then
      git init -q "$SRC"
      git -C "$SRC" remote add origin "$TRANSCODA_URL"
    fi
    git -C "$SRC" fetch -q --depth 1 origin "$TRANSCODA_COMMIT"
    git -C "$SRC" checkout -q --force FETCH_HEAD
    done_ "checked out Transcoda ${TRANSCODA_COMMIT:0:7} in $SRC"
  else
    already "Transcoda source at ${TRANSCODA_COMMIT:0:7} in $SRC"
  fi
  if git -C "$SRC" apply --check --reverse "$PATCH" 2>/dev/null; then
    already "train.py can start from saved weights"
  elif git -C "$SRC" apply "$PATCH"; then
    done_ "patched train.py so it can start from saved weights"
  else
    failed "transcoda-init-from.patch doesn't apply to $SRC"
  fi
  # The released checkpoint names its encoder by a path under weights/, as the bench's copy has it.
  if [ ! -e "$SRC/weights" ]; then
    ln -s "$OMR/transcoda/weights" "$SRC/weights" && done_ "linked the released weights into $SRC/weights"
  fi
}

setup_python() {
  local py="$SRC/.venv/bin/python"
  if "$py" -c 'import torch, lightning, verovio; assert torch.cuda.is_available()' 2>/dev/null; then
    already "training environment in $SRC/.venv"
    return
  fi
  if ! have uv; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null && done_ "installed uv"
  fi
  # uv sync installs the PyPI build of torch; the CUDA 13 build is what drives the Spark's GPU.
  if (cd "$SRC" && uv sync -q --group grammar) && \
     uv pip install -q --python "$py" --reinstall torch==2.9.1 torchvision==0.24.1 --index-url "$TORCH_INDEX"; then
    if "$py" -c 'import torch; assert torch.cuda.is_available()' 2>/dev/null; then
      done_ "made the training environment in $SRC/.venv"
    else
      failed "the training environment installed but torch can't see the GPU; run: $py -c 'import torch; print(torch.cuda.is_available())'"
    fi
  else
    failed "the training environment didn't install; the uv error is above"
  fi
}

setup_humlib() {
  if [ -x "$TRAIN/humlib/bin/musicxml2hum" ]; then
    already "musicxml2hum built in $TRAIN/humlib/bin"
    return
  fi
  [ -d "$TRAIN/humlib/.git" ] || git clone -q --depth 1 https://github.com/craigsapp/humlib "$TRAIN/humlib"
  if (cd "$TRAIN/humlib" && make -s -j"$(nproc)" library >/dev/null && make -s -j"$(nproc)" musicxml2hum >/dev/null); then
    done_ "built musicxml2hum"
  else
    failed "musicxml2hum didn't build; the make error is above"
  fi
}

setup_musescore() {
  # String Quartets ship as MuseScore files, so MuseScore turns them into MusicXML.
  local target="$TRAIN/MuseScore" homr_copy="$OMR/homr-train/homr/datasets/MuseScore"
  if [ -x "$target" ]; then
    already "MuseScore for aarch64 in $target"
  elif [ -x "$homr_copy" ]; then
    ln -s "$homr_copy" "$target" && done_ "using the MuseScore already downloaded for homr training"
  elif curl -fsSL -o "$target.part" "$MUSESCORE_URL"; then
    mv "$target.part" "$target" && chmod 755 "$target" && done_ "downloaded MuseScore 4.6.5 for aarch64"
  else
    rm -f "$target.part"
    failed "MuseScore didn't download from $MUSESCORE_URL"
  fi
}

# --- training pages (run inside the background job) --------------------------
py() { (cd "$SRC" && "$SRC/.venv/bin/python" "$@"); }

clone_source() {
  local url="$1" dir="$2"
  [ -d "$dir/.git" ] || git clone -q --depth 1 "$url" "$dir"
}

kern_from_xml() {
  local name="$1"
  local base="$INTERIM/$name"
  [ -n "$(ls -A "$base/1_kern_conversions" 2>/dev/null)" ] && return 0
  (cd "$SRC" && bash scripts/dataset_generation/kern_conversions/convert_xml_to_kern.sh \
    "$base/0_raw_xml" "$base/1_kern_conversions")
}

filter_and_normalize() {
  local base="$INTERIM/$1"
  if [ -z "$(ls -A "$base/2_filtered" 2>/dev/null)" ]; then
    py -m scripts.dataset_generation.filtering.main "$base/1_kern_conversions/" "$base/2_filtered/" --workers "$(nproc)"
  fi
  if [ -z "$(ls -A "$base/3_normalized" 2>/dev/null)" ]; then
    py -m scripts.dataset_generation.normalization.main --input_dir "$base/2_filtered" \
      --output_dir "$base/3_normalized" --workers "$(nproc)"
  fi
  say "$1: $(ls "$base/3_normalized" | wc -l) scores ready to draw"
}

build_scores() {
  mkdir -p "$SOURCES" "$INTERIM"
  say "fetching OpenScore Lieder and String Quartets"
  clone_source https://github.com/OpenScore/Lieder "$SOURCES/Lieder"
  clone_source https://github.com/OpenScore/StringQuartets "$SOURCES/StringQuartets"

  if [ -z "$(ls -A "$INTERIM/openscore-lieder/0_raw_xml" 2>/dev/null)" ]; then
    py -m scripts.dataset_generation.extract_raw_data.extract_openscore_xml --dataset lieder \
      --input_dir "$SOURCES/Lieder/scores" --output_dir "$INTERIM/openscore-lieder/0_raw_xml"
  fi
  if [ -z "$(ls -A "$INTERIM/openscore-stringquartets/0_raw_xml" 2>/dev/null)" ]; then
    # MuseScore draws with no screen attached, and runs without mounting its AppImage.
    QT_QPA_PLATFORM=offscreen APPIMAGE_EXTRACT_AND_RUN=1 \
      py -m scripts.dataset_generation.extract_raw_data.extract_openscore_xml --dataset stringquartets \
      --musescore_cmd "$TRAIN/MuseScore" --input_dir "$SOURCES/StringQuartets/scores" \
      --output_dir "$INTERIM/openscore-stringquartets/0_raw_xml"
  fi
  kern_from_xml openscore-lieder
  kern_from_xml openscore-stringquartets

  if [ -z "$(ls -A "$INTERIM/grandstaff/1_kern_conversions" 2>/dev/null)" ]; then
    say "fetching GrandStaff"
    py -m scripts.dataset_generation.extract_raw_data.extract_grandstaff_transcriptions \
      --split train --output_dir "$TRAIN/data/interim"
    (cd "$SRC" && bash scripts/dataset_generation/kern_conversions/convert_ekern_to_kern.sh \
      "$INTERIM/grandstaff/0_raw_ekern" "$INTERIM/grandstaff/1_kern_conversions")
  fi

  local name
  for name in openscore-lieder openscore-stringquartets grandstaff; do
    filter_and_normalize "$name"
  done
}

draw_pages() {
  local split="$1" count="$2" seed="$3"
  local out="$PAGES/$split"
  [ -f "$out/.ready" ] && { say "$split pages already drawn"; return 0; }
  say "drawing $count $split pages"
  py -m scripts.dataset_generation.dataset_generation.main \
    "$INTERIM/openscore-lieder/3_normalized" \
    "$INTERIM/openscore-stringquartets/3_normalized" \
    "$INTERIM/grandstaff/3_normalized" \
    --output_dir "$out" --target_samples "$count" --num_workers "$(nproc)" \
    --artifacts_out_dir "$PAGES/_runs" --base_seed "$seed" --quiet true
  # Pages whose answer is longer than the model can write are dropped.
  py scripts/dataset_generation/filter_by_seq_len.py "$out" ./vocab/bpe3k-splitspaces "$MAX_TOKENS"
  rm -rf "${out}_pre_filter_backup"
  touch "$out/.ready"
}

write_config() {
  "$SRC/.venv/bin/python" - "$SRC/config/train.json" "$TRAIN/finetune.json" "$PAGES" "$RUN" <<'PY'
import json, sys
source, target, pages, run = sys.argv[1:]
config = json.load(open(source))
config["data"]["train_path"] = f"{pages}/train"
config["data"]["validation_paths"] = {"synth": f"{pages}/check"}
config["checkpoint"].update(dirpath=run, filename="transcoda-spark", run_name="transcoda-spark",
                            monitor="val/synth/CER_no_ties_beams")
config["optimizer"].update(learning_rate=0.0002, warmup_steps=100)
training = config["training"]
# OMR-NED during training needs the omr-ned packages; the bench scores OMR-NED instead.
training.update(max_epochs=2, compile_model=False, compute_omr_ned=False, frequent_validation_set_names=["synth"],
                frequent_validation_subset_sizes={"synth": 256})
json.dump(config, open(target, "w"), indent=2)
PY
}

run_job() {
  say "building the training pages"
  build_scores
  draw_pages check "$CHECK_PAGES" 1
  draw_pages train "$TRAIN_PAGES" 0
  write_config
  local start=(--init_from="$RELEASED")
  # A run that already saved a checkpoint carries on from it instead.
  [ -f "$RUN/last.ckpt" ] && start=(--checkpoint.auto_resume=true)
  say "training"
  WANDB_MODE=offline WANDB_DIR="$TRAIN" py train.py "$TRAIN/finetune.json" "${start[@]}"
}

# --- control -------------------------------------------------------------------
start_job() {
  local pid
  if pid=$(running_pid); then
    already "page building or training is running (process $pid); see progress with: $0 status"
    return
  fi
  local free_gb
  free_gb=$(df -BG --output=avail "$TRAIN" | tail -1 | tr -dc 0-9)
  [ "$free_gb" -ge "$MIN_FREE_GB" ] || { failed "only ${free_gb} GB free in $TRAIN; ${MIN_FREE_GB} GB is needed for the training pages"; return; }

  local cap=()
  if have systemd-run && systemd-run --user --scope -q -p MemoryMax="$TRAIN_MEMORY" true 2>/dev/null; then
    cap=(systemd-run --user --scope -q -p MemoryMax="$TRAIN_MEMORY")
  fi
  echo "$(date '+%Y-%m-%d %H:%M') started" >"$LASTRUN"
  # The wrapper records how the job ended, so status can tell finished, failed and never started apart.
  setsid nohup "${cap[@]}" nice -n 10 bash -c '
    bash "$1" _job; code=$?
    if [ "$code" -eq 0 ]; then how="finished"; else how="stopped with exit code $code"; fi
    echo "$(date "+%Y-%m-%d %H:%M") $how" >"$2"
  ' _ "$REPO/omr_bench/spark_transcoda.sh" "$LASTRUN" </dev/null >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  sleep 5
  if pid=$(running_pid); then
    done_ "started in the background (process $pid). It builds the training pages first, then trains"
    echo "This terminal is free. Progress: bash $REPO/omr_bench/spark_transcoda.sh status"
  else
    failed "it stopped straight away; the end of $LOG says why"
    tail -20 "$LOG" >&2 || true
  fi
}

show_status() {
  local pid
  if pid=$(running_pid); then
    echo "Running (process $pid)."
  elif [ ! -f "$LASTRUN" ]; then
    echo "Never started on this machine. Start it with: bash $REPO/omr_bench/spark_transcoda.sh"
    return 0
  else
    echo "Not running. Last run: $(cat "$LASTRUN")."
    [ -n "$(best_checkpoint)" ] && echo "Best checkpoint so far: $(best_checkpoint). Add it to the bench with: bash $REPO/omr_bench/spark_transcoda.sh export"
  fi
  [ -f "$LOG" ] || return 0
  echo
  echo "Latest steps:"
  tr '\r' '\n' <"$LOG" | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{5} ' | tail -4 | sed 's/^/  /'
  echo
  echo "Last log line:"
  tr '\r' '\n' <"$LOG" | grep -v '^\s*$' | tail -1
  have nvidia-smi && { echo; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader | sed 's/^/GPU busy, memory: /'; }
}

stop_job() {
  local pid
  if pid=$(running_pid); then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
    done_ "stopped. Carry on from the last saved checkpoint with: bash $REPO/omr_bench/spark_transcoda.sh"
  else
    already "nothing was running"
  fi
}

export_model() {
  local model
  model=$(best_checkpoint)
  [ -n "$model" ] || die "no trained checkpoint yet. See: bash $REPO/omr_bench/spark_transcoda.sh status"
  local engines="$REPO/omr_bench/engines.toml"
  # The section names the checkpoint, so it is rewritten whenever a better one exists.
  "$OMR/bench-venv/bin/python" - "$engines" "$model" "$SRC" <<'PY'
import re, sys
path, model, src = sys.argv[1:]
text = open(path).read()
text = re.sub(r"\n*\[engines\.transcoda-spark\]\n(?:(?!\[).*\n?)*", "\n", text).rstrip() + "\n"
text += f'''
[engines.transcoda-spark]
# Transcoda trained further on the Spark by spark_transcoda.sh.
# --no-sync keeps the CUDA build of torch that uv sync would swap back.
command = ["uv", "run", "--no-sync", "--directory", "{src}", "scripts/inference.py",
           "--weights", "{model}", "--image", "{{image}}"]
output = "*_pred.krn"
kern_header = true
'''
open(path, "w").write(text)
PY
  done_ "added transcoda-spark to omr_bench/engines.toml with $(basename "$model")"
  echo "Score it against the other readers with: bash $REPO/omr_bench/spark_bench.sh run"
}

case "$MODE" in
  start)
    setup_system
    setup_source
    setup_python
    setup_humlib
    setup_musescore
    [ ${#FAILED[@]} -eq 0 ] || die "setup failed, so nothing was started."
    start_job
    ;;
  _job) run_job ;;
  status) show_status ;;
  stop) stop_job ;;
  export) export_model ;;
  *) die "unknown mode '$MODE'. Use no argument to start, or: status, stop, export" ;;
esac
