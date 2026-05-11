#!/usr/bin/env bash

set -euo pipefail

find_pg_bin_dir() {
    if command -v initdb >/dev/null 2>&1 && command -v pg_ctl >/dev/null 2>&1; then
        dirname "$(command -v initdb)"
        return 0
    fi

    local candidate
    candidate=$(find /usr/lib/postgresql -type f -name initdb 2>/dev/null | sort -V | tail -1 || true)
    if [ -n "${candidate:-}" ]; then
        dirname "$candidate"
        return 0
    fi

    return 1
}

run_privileged() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
        return
    fi

    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        sudo "$@"
        return
    fi

    echo "::error::PostgreSQL is not installed and this runner has no non-interactive sudo."
    exit 1
}

install_postgres_if_missing() {
    if find_pg_bin_dir >/dev/null 2>&1; then
        return
    fi

    if command -v apt-get >/dev/null 2>&1; then
        run_privileged apt-get update
        run_privileged env DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql
        return
    fi

    if command -v apk >/dev/null 2>&1; then
        run_privileged apk add --no-cache postgresql16 postgresql16-client
        return
    fi

    echo "::error::Unable to install PostgreSQL on this runner."
    exit 1
}

install_postgres_if_missing

PG_BIN_DIR=$(find_pg_bin_dir)
export PATH="${PG_BIN_DIR}:$PATH"
export PGHOST=127.0.0.1
export PGPORT=5432
export PGUSER=postgres
export PGDATABASE=facturascripts
export PG_RUN_AS_POSTGRES=0

PGDATA_DIR="${RUNNER_TEMP:-/tmp}/pgdata"
PGSOCKET_DIR="${RUNNER_TEMP:-/tmp}/pgsocket"
PGLOG_FILE="${PGDATA_DIR}/postgresql.log"
mkdir -p "$PGDATA_DIR"
mkdir -p "$PGSOCKET_DIR"
find "$PGDATA_DIR" -mindepth 1 -delete
find "$PGSOCKET_DIR" -mindepth 1 -delete

run_pg_command() {
    if [ "$(id -u)" -ne 0 ]; then
        "$@"
        return
    fi

    if ! id postgres >/dev/null 2>&1; then
        echo "::error::The postgres system user is missing after installation."
        exit 1
    fi

    if ! command -v runuser >/dev/null 2>&1; then
        echo "::error::runuser is required when the runner executes as root."
        exit 1
    fi

    export PG_RUN_AS_POSTGRES=1
    chown -R postgres:postgres "$PGDATA_DIR" "$PGSOCKET_DIR"
    runuser -u postgres -- env \
        PATH="$PATH" \
        PGHOST="$PGHOST" \
        PGPORT="$PGPORT" \
        PGUSER="$PGUSER" \
        PGDATABASE="$PGDATABASE" \
        "$@"
}

run_pg_command initdb -D "$PGDATA_DIR" --username="$PGUSER" --auth=trust >/dev/null
cat >> "$PGDATA_DIR/postgresql.conf" <<EOF
listen_addresses = '127.0.0.1'
port = ${PGPORT}
unix_socket_directories = '${PGSOCKET_DIR}'
fsync = off
synchronous_commit = off
full_page_writes = off
max_connections = 200
EOF

if ! run_pg_command pg_ctl -D "$PGDATA_DIR" -l "$PGLOG_FILE" -w start >/dev/null; then
    [ -f "$PGLOG_FILE" ] && cat "$PGLOG_FILE"
    exit 1
fi

run_pg_command createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE"

{
    echo "PATH=${PG_BIN_DIR}:$PATH"
    echo "PGHOST=$PGHOST"
    echo "PGPORT=$PGPORT"
    echo "PGUSER=$PGUSER"
    echo "PGDATABASE=$PGDATABASE"
    echo "PGDATA_DIR=$PGDATA_DIR"
    echo "PGSOCKET_DIR=$PGSOCKET_DIR"
    echo "PGLOG_FILE=$PGLOG_FILE"
    echo "PG_RUN_AS_POSTGRES=$PG_RUN_AS_POSTGRES"
} >> "$GITHUB_ENV"
