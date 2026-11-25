#!/usr/bin/env bash
# The oldest glibc the native code under each PATH runs on: the newest GLIBC_ symbol version
# its ELF files reference; nothing when none references glibc. Shell launchers and other text
# are not ELF and are skipped; an ELF file objdump cannot read fails the scan.
#
#   glibc-floor.sh PATH...
set -euo pipefail

find "$@" -type f \( -name '*.so' -o -name '*.so.*' -o -perm -u+x \) -print0 \
  | while IFS= read -r -d '' file; do
      if [[ "$(head -c 4 -- "$file" | od -An -tx1 | tr -d ' \n')" == 7f454c46 ]]; then
        printf '%s\0' "$file"
      fi
    done \
  | xargs -0 --no-run-if-empty objdump -p \
  | { grep -o 'GLIBC_[0-9][0-9.]*' || true; } | cut -d_ -f2 | sort -uV | tail -n 1
