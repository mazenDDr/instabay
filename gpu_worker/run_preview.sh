#!/bin/sh
# NFR-06: capture process exit even when a native process is killed by the OS.
set -u
cd "$HOME/instabay-native" || exit 1
INSTABAY_GPU_ENABLED=1 "$HOME/miniconda3/envs/main/bin/python" -u wan_preview.py \
  --spec "$1" --confirm-gpu
preview_exit=$?
printf '\n[exit %s]\n' "$preview_exit"
exit "$preview_exit"
