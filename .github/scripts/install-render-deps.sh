#!/usr/bin/env bash
# Install LibreOffice and poppler for the render job, surviving an Ubuntu mirror
# outage.
#
# The job caches the downloaded .debs (ARCHIVES) and the package lists they
# were resolved from (LISTS) together. When the mirror answers, apt works as
# usual and refreshes LISTS. When it doesn't -- a runner that can't resolve
# the mirror's name, say -- apt installs from the cached lists and .debs
# without touching the network. Without the lists, `apt-get install` can't
# find the packages at all, even with every .deb on disk.
#
# Usage: install-render-deps.sh ARCHIVES LISTS
set -euo pipefail

archives=${1:?archives dir}
lists=${2:?lists dir}
# RENDER_PACKAGES overrides the list, to try the script on something small.
read -ra packages <<<"${RENDER_PACKAGES:-libreoffice-impress poppler-utils}"
mkdir -p "$archives/partial" "$lists"

# --error-on=any: by default apt-get update exits 0 when it couldn't fetch a
# single index, and the failure only shows later as "Unable to locate package".
if sudo apt-get update -o Acquire::Retries=3 --error-on=any; then
  # Keep the lists the .debs in this install are resolved from.
  rm -rf "${lists:?}"/*
  sudo find /var/lib/apt/lists -maxdepth 1 -type f ! -name lock -exec cp -t "$lists" {} +
elif [ -n "$(ls -A "$lists")" ]; then
  echo "::warning::The Ubuntu mirror is unreachable; installing from the cached package lists and .debs."
  sudo cp -t /var/lib/apt/lists "$lists"/*
else
  echo "::error::The Ubuntu mirror is unreachable and there are no cached package lists to install from."
  exit 1
fi

sudo apt-get install -y --no-install-recommends -o Dir::Cache::Archives="$archives" "${packages[@]}"
sudo chown -R "$(id -un)" "$archives" "$lists"
