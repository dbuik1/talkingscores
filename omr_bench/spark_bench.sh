#!/usr/bin/env bash
# Install the score-reader test bench and the readers it compares, then run it.
#
# Run on: the DGX Spark, as David's own user (the one with sudo), in bash,
#         after agent-kit's runner/spark-setup.sh has run there.
# Usage:  spark_bench.sh          install everything and read one page with each reader
#         spark_bench.sh run      read every page with every reader and write the scores
# Changes: everything lives in ~/omr (about 30 GB with the models): a JDK, the
#          bench and its own Python environment, Audiveris, homr, Transcoda and
#          LEGATO. Installs libcairo2, fontconfig and freetype with apt, and
#          Verovio's Leipzig font in ~/.local/share/fonts. Nothing else on the
#          machine changes. Undo: rm -rf ~/omr.
# Readers run under a 24 GB memory cap so CI and the local models keep their room.
# Safe to run again: finished steps are reported and skipped.

set -euo pipefail

MODE="${1:-setup}"
OMR="$HOME/omr"
REPO_URL="https://github.com/dbuik1/talkingscores"
REPO="$OMR/talkingscores"
JDK="$OMR/jdk"
JDK_URL="https://api.adoptium.net/v3/binary/latest/25/ga/linux/aarch64/jdk/hotspot/normal/eclipse"
TESSDATA="$OMR/tessdata"
TESS_LANGS="eng deu fra ita"
TORCH_INDEX="https://download.pytorch.org/whl/cu130"
READER_MEMORY="24G"
MIN_FREE_GB=40

DONE=(); ALREADY=(); FAILED=()
done_() { DONE+=("$1"); echo "done: $1"; }
already() { ALREADY+=("$1"); echo "already: $1"; }
failed() { FAILED+=("$1"); echo "FAILED: $1" >&2; }
die() { echo "Stopped: $1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

summary() {
  echo
  echo "Summary"
  for line in "${DONE[@]+"${DONE[@]}"}"; do echo "  changed: $line"; done
  for line in "${ALREADY[@]+"${ALREADY[@]}"}"; do echo "  already fine: $line"; done
  for line in "${FAILED[@]+"${FAILED[@]}"}"; do echo "  failed: $line"; done
  [ ${#FAILED[@]} -eq 0 ] || echo "  Send this summary back to Claude to fix the failed steps."
}
trap summary EXIT

capped() {
  if have systemd-run && systemd-run --user --scope -q -p MemoryMax="$READER_MEMORY" true 2>/dev/null; then
    systemd-run --user --scope -q -p MemoryMax="$READER_MEMORY" "$@"
  else
    "$@"
  fi
}

# --- preconditions -----------------------------------------------------------
[ "$(uname -m)" = aarch64 ] || die "this is for the DGX Spark (aarch64); this machine is $(uname -m)."
have git || die "git isn't installed. Run: sudo apt-get install -y git"
have curl || die "curl isn't installed. Run: sudo apt-get install -y curl"

# A clone left at an older commit would run the old steps, so update it and
# restart on the new copy before doing anything else.
if [ -z "${OMR_SCRIPT_UPDATED:-}" ] && [ -d "$REPO/.git" ]; then
  before=$(git -C "$REPO" rev-parse HEAD)
  if git -C "$REPO" pull -q --ff-only; then
    if [ "$(git -C "$REPO" rev-parse HEAD)" != "$before" ]; then
      echo "updated talkingscores to $(git -C "$REPO" rev-parse --short HEAD); restarting with the new script"
      OMR_SCRIPT_UPDATED=1 exec bash "$REPO/omr_bench/spark_bench.sh" "$@"
    fi
  else
    echo "couldn't update $REPO with git pull; carrying on with the copy on disk" >&2
  fi
fi
have nvidia-smi && nvidia-smi >/dev/null 2>&1 || die "the GPU isn't answering. Run nvidia-smi to see why, or run agent-kit's spark-setup.sh first."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "Python 3.11 or newer is needed. Run: sudo apt-get install -y python3"
python3 -m venv --help >/dev/null 2>&1 || die "Python venv is missing. Run: sudo apt-get install -y python3-venv"
mkdir -p "$OMR"
free_gb=$(df -BG --output=avail "$OMR" | tail -1 | tr -dc 0-9)
[ "$MODE" = run ] || [ "$free_gb" -ge "$MIN_FREE_GB" ] || die "only ${free_gb} GB free in $OMR; ${MIN_FREE_GB} GB is needed."

# --- the bench itself ---------------------------------------------------------
setup_bench() {
  local missing=()
  for pkg in libcairo2 fontconfig libfreetype6; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    sudo apt-get install -y -qq "${missing[@]}" >/dev/null && done_ "installed ${missing[*]}"
  else
    already "Cairo, fontconfig and FreeType installed"
  fi

  if [ -d "$REPO/.git" ]; then
    git -C "$REPO" pull -q --ff-only && already "talkingscores clone in $REPO (updated)"
  else
    git clone -q --depth 1 "$REPO_URL" "$REPO" && done_ "cloned talkingscores into $REPO"
  fi

  if [ ! -x "$OMR/bench-venv/bin/python" ]; then
    python3 -m venv "$OMR/bench-venv"
    done_ "made the bench's Python environment"
  fi
  "$OMR/bench-venv/bin/pip" install -q -r "$REPO/omr_bench/requirements.txt"
  already "bench packages match omr_bench/requirements.txt"

  if [ ! -f "$REPO/omr_bench/engines.toml" ]; then
    cp "$REPO/omr_bench/engines.example.toml" "$REPO/omr_bench/engines.toml"
    done_ "wrote omr_bench/engines.toml from the example"
  else
    already "omr_bench/engines.toml exists (kept as it is)"
  fi
}

# --- readers -------------------------------------------------------------------
setup_audiveris() {
  if [ ! -x "$JDK/bin/java" ]; then
    mkdir -p "$JDK"
    curl -fsSL "$JDK_URL" | tar -xz -C "$JDK" --strip-components 1
    done_ "installed JDK 25 in $JDK"
  else
    already "JDK $("$JDK/bin/java" -version 2>&1 | head -1 | cut -d'"' -f2) in $JDK"
  fi

  mkdir -p "$TESSDATA"
  for lang in $TESS_LANGS; do
    [ -s "$TESSDATA/$lang.traineddata" ] || curl -fsSL -o "$TESSDATA/$lang.traineddata" \
      "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$lang.traineddata"
  done
  already "lyric and title text data for: $TESS_LANGS"

  if [ -x "$OMR/audiveris/bin/Audiveris" ]; then
    already "Audiveris built in $OMR/audiveris"
    return
  fi
  local src="$OMR/audiveris-src"
  [ -d "$src/.git" ] || git clone -q --depth 1 https://github.com/Audiveris/audiveris.git "$src"
  if (cd "$src" && JAVA_HOME="$JDK" ./gradlew -q build -x test); then
    local archive
    archive=$(ls "$src"/app/build/distributions/*.tar | head -1)
    mkdir -p "$OMR/audiveris"
    tar -xf "$archive" -C "$OMR/audiveris" --strip-components 1
    done_ "built Audiveris from source into $OMR/audiveris"
  else
    failed "Audiveris didn't build; see the Gradle output above"
  fi
}

torch_venv() {
  local venv="$1"
  [ -x "$venv/bin/python" ] || python3 -m venv "$venv"
  if ! "$venv/bin/python" -c 'import torch; assert torch.cuda.is_available()' 2>/dev/null; then
    "$venv/bin/pip" install -q torch torchvision --index-url "$TORCH_INDEX"
  fi
}

setup_homr() {
  if [ -x "$OMR/homr-venv/bin/homr" ]; then
    already "homr installed in $OMR/homr-venv"
    return
  fi
  if torch_venv "$OMR/homr-venv" && "$OMR/homr-venv/bin/pip" install -q homr; then
    done_ "installed homr in $OMR/homr-venv"
  else
    failed "homr didn't install"
  fi
}

setup_transcoda() {
  local dir="$OMR/transcoda"
  if ! have uv && [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
    done_ "installed uv"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  [ -d "$dir/.git" ] || { git clone -q --depth 1 https://github.com/btrkeks/transcoda "$dir" && done_ "cloned Transcoda"; }
  if (cd "$dir" && uv sync -q --group grammar); then
    already "Transcoda packages synced"
  else
    failed "Transcoda packages didn't install (uv sync)"
    return
  fi
  if [ ! -e "$dir/weights/model.ckpt" ]; then
    "$OMR/bench-venv/bin/hf" download btrkeks/transcoda-59M-zeroshot-v1 --local-dir "$dir/weights" >/dev/null
    local checkpoint
    checkpoint=$(find "$dir/weights" -name '*.ckpt' | head -1)
    if [ -n "$checkpoint" ]; then
      [ "$checkpoint" = "$dir/weights/model.ckpt" ] || ln -s "$checkpoint" "$dir/weights/model.ckpt"
      done_ "downloaded Transcoda weights"
    else
      failed "Transcoda weights downloaded but no .ckpt file was in them; look in $dir/weights"
    fi
  else
    already "Transcoda weights in $dir/weights"
  fi
}

setup_legato() {
  local dir="$OMR/legato"
  [ -d "$dir/.git" ] || { git clone -q --depth 1 https://github.com/guang-yng/legato "$dir" && done_ "cloned LEGATO"; }
  if "$OMR/legato-venv/bin/python" -c 'import transformers' 2>/dev/null; then
    already "LEGATO packages installed"
    return
  fi
  # Its requirements pin an x86 CUDA build of torch; the Spark keeps the aarch64 one.
  # They also fetch musicdiff over SSH, which needs a GitHub key; the repo is public, so HTTPS works without one.
  if torch_venv "$OMR/legato-venv" && \
     grep -v -E '^(torch|torchvision|torchaudio)([=<>~ ]|$)' "$dir/requirements.txt" | \
       sed -E 's#git\+ssh://git@github\.com/#git+https://github.com/#' > "$OMR/legato-requirements.txt" && \
     "$OMR/legato-venv/bin/pip" install -q -r "$OMR/legato-requirements.txt"; then
    done_ "installed LEGATO's packages"
  else
    failed "LEGATO's packages didn't install"
  fi
}

# --- running -----------------------------------------------------------------
bench() { (cd "$REPO" && JAVA_HOME="$JDK" TESSDATA_PREFIX="$TESSDATA" "$OMR/bench-venv/bin/python" -m omr_bench.bench "$@"); }

build_sets() {
  if [ -f "$REPO/omr_bench/sets/ours/manifest.csv" ]; then
    already "our 20-page set is built"
  else
    bench build && done_ "built our 20-page set; print omr_bench/sets/ours/print/all-pages.pdf to add phone photos"
  fi
  if [ -f "$REPO/omr_bench/sets/smb/manifest.csv" ]; then
    already "Sheet Music Benchmark downloaded"
  elif "$OMR/bench-venv/bin/hf" auth whoami >/dev/null 2>&1; then
    bench fetch-smb && done_ "downloaded the Sheet Music Benchmark" || \
      failed "Sheet Music Benchmark didn't download. Request access at https://huggingface.co/datasets/PRAIG/SMB, then run this again"
  else
    failed "not signed in to Hugging Face, so the Sheet Music Benchmark was skipped. Request access at https://huggingface.co/datasets/PRAIG/SMB, then run: $OMR/bench-venv/bin/hf auth login"
  fi
}

readers() { grep -oE '^\[engines\.[a-z0-9_-]+\]' "$REPO/omr_bench/engines.toml" | sed -E 's/\[engines\.(.*)\]/\1/'; }

smoke_test() {
  for reader in $(readers); do
    [ "$reader" = flat ] && [ -z "${FLAT_TOKEN:-}" ] && { already "Flat skipped (no FLAT_TOKEN set)"; continue; }
    local output
    output=$(capped bash -c "cd '$REPO' && JAVA_HOME='$JDK' TESSDATA_PREFIX='$TESSDATA' '$OMR/bench-venv/bin/python' -m omr_bench.bench run --engine '$reader' --limit 1 --force" 2>&1 || true)
    echo "$output"
    if grep -q ': read (' <<<"$output"; then
      done_ "$reader read a test page"
    else
      failed "$reader couldn't read a test page; its error is in the line above"
    fi
  done
}

full_run() {
  for set in ours smb; do
    [ -f "$REPO/omr_bench/sets/$set/manifest.csv" ] || continue
    for reader in $(readers); do
      [ "$reader" = flat ] && [ -z "${FLAT_TOKEN:-}" ] && continue
      capped bash -c "cd '$REPO' && JAVA_HOME='$JDK' TESSDATA_PREFIX='$TESSDATA' '$OMR/bench-venv/bin/python' -m omr_bench.bench run --set omr_bench/sets/$set --engine '$reader'" \
        || failed "$reader stopped part-way through the $set pages"
    done
    bench score --set "omr_bench/sets/$set" && done_ "scored the $set pages: $REPO/omr_bench/runs/$set/summary.md"
  done
}

case "$MODE" in
  setup)
    setup_bench
    setup_audiveris
    setup_homr
    setup_transcoda
    setup_legato
    build_sets
    smoke_test
    echo
    echo "Next: run every page with every reader by running this script again with: run"
    ;;
  run)
    [ -x "$OMR/bench-venv/bin/python" ] || die "the bench isn't installed yet. Run this script with no arguments first."
    full_run
    ;;
  *)
    die "unknown mode '$MODE'. Use no argument to install, or: run"
    ;;
esac
