#!/bin/sh
set -e

# When the container starts as root, remap the bookotter user to PUID/PGID
# (unraid's nobody:users by default), fix ownership of the data directory,
# and drop privileges. When started with --user, run as that user directly.
if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-99}"
    PGID="${PGID:-100}"

    groupmod -o -g "$PGID" bookotter
    usermod -o -u "$PUID" bookotter

    chown -R "$PUID:$PGID" /app/data

    exec gosu bookotter "$@"
fi

exec "$@"
