#!/bin/sh
# Install Debian packages over a network that may drop connections (proxies that reset mid-download).
# The index update and the downloads are retried; packages already fetched stay in apt's cache between
# tries (the base image's docker-clean hook only empties it after an update or a dpkg run), and the
# install itself then runs from that cache.
# Usage: apt-install PACKAGE...
set -e

retry() {
  tries=$1; shift
  n=1
  until "$@"; do
    [ "$n" -lt "$tries" ] || { echo "apt-install: '$*' failed $tries times, giving up" >&2; return 1; }
    echo "apt-install: '$*' failed (try $n of $tries), trying again in 20 s" >&2
    n=$((n + 1))
    sleep 20
  done
}

retry 6 apt-get update
retry 10 apt-get install -y --no-install-recommends --download-only "$@"
apt-get install -y --no-install-recommends "$@"
rm -rf /var/lib/apt/lists/*
