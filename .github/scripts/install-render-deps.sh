#!/usr/bin/env bash
# Install LibreOffice and poppler for the render job, without depending on the
# runner image's apt configuration or on the Ubuntu mirror being reachable.
#
# - apt reads only Ubuntu's `main` component -- where LibreOffice, poppler and
#   all their dependencies live -- from archive.ubuntu.com and
#   security.ubuntu.com. The image's own sources point at a mirror that
#   Namespace runners can't always resolve, and add universe and third-party
#   repositories whose indexes are many times larger.
# - The package lists (LISTS) and downloaded .debs (ARCHIVES) live in folders
#   the job caches together. When the mirror can't be reached, apt installs
#   from the cached lists and .debs without the network. Without the lists,
#   `apt-get install` can't find the packages at all, even with every .deb on
#   disk.
#
# Usage: install-render-deps.sh ARCHIVES LISTS
# RENDER_PACKAGES overrides the package list, to try the script on something small.
set -euo pipefail

archives=${1:?archives dir}
lists=${2:?lists dir}
read -ra packages <<<"${RENDER_PACKAGES:-libreoffice-impress poppler-utils}"
mkdir -p "$archives/partial" "$lists/partial"

# shellcheck source=/dev/null
codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
arch=$(dpkg --print-architecture)
sources=$(mktemp -d)
cat >"$sources/render-deps.sources" <<SOURCES
Types: deb
URIs: http://archive.ubuntu.com/ubuntu
Suites: $codename $codename-updates
Components: main
Architectures: $arch
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg

Types: deb
URIs: http://security.ubuntu.com/ubuntu
Suites: $codename-security
Components: main
Architectures: $arch
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
SOURCES

apt_options=(
  -o Dir::Etc::SourceList=/dev/null
  -o Dir::Etc::SourceParts="$sources"
  -o Dir::State::Lists="$lists"
  -o Dir::Cache::Archives="$archives"
  -o Acquire::Languages=none
  -o Acquire::Retries=3
  -o Acquire::http::Timeout=30 # a stalled download fails instead of hanging the job
)

# --error-on=any: by default apt-get update exits 0 when it couldn't fetch a
# single index, and the failure only shows later as "Unable to locate package".
if sudo apt-get update "${apt_options[@]}" --error-on=any; then
  :
elif compgen -G "$lists/*_Packages*" >/dev/null; then
  echo "::warning::The Ubuntu mirror is unreachable; installing from the cached package lists and .debs."
else
  echo "::error::The Ubuntu mirror is unreachable and there are no cached package lists to install from."
  exit 1
fi

sudo apt-get install -y --no-install-recommends "${apt_options[@]}" "${packages[@]}"
sudo chown -R "$(id -un)" "$archives" "$lists"
