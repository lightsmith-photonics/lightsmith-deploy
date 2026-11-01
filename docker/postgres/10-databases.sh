#!/bin/sh
# Runs once, when the Postgres volume is first initialised: one login role and one database per
# product, each owned by its role and closed to the others. Passwords come from the environment (.env).
set -eu

create() {
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -v name="$1" -v pass="$2" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'name', :'pass') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'name', :'name') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'name') \gexec
SQL
}

create community "$COMMUNITY_DB_PASSWORD"
create cloud "$CLOUD_DB_PASSWORD"
create materials "$MATERIALS_DB_PASSWORD"
