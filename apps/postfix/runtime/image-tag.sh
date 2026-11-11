#!/bin/sh
set -eu
# Reversible encoding: underscores aren't valid in Debian package versions.
version=${1:?pass installed Debian Postfix package version}
revision=${2:?pass runtime revision}
case "$version" in
  [0-9]*) ;;
  *) exit 1 ;;
esac
case "$version" in *[!a-zA-Z0-9.+:~-]*) exit 1 ;; esac
case "$revision" in ''|*[!0-9]*|0*) exit 1 ;; esac
tag=$(printf '%s' "$version" | sed -e 's/+/_plus_/g' -e 's/:/_epoch_/g' -e 's/~/_tilde_/g')
tag="$tag-r$revision"
test "${#tag}" -le 128
printf '%s\n' "$tag"
