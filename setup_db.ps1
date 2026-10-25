# One-time database setup. Usage: .\setup_db.ps1 -Password 1234
param([string]$Password = "1234", [string]$DbUser = "postgres")
$env:PGPASSWORD = $Password
createdb -U $DbUser -h localhost ancient_trials
psql -U $DbUser -h localhost -d ancient_trials -c "CREATE EXTENSION IF NOT EXISTS btree_gist;"
psql -U $DbUser -h localhost -d ancient_trials -f backend/db/migrations/001_init.sql
psql -U $DbUser -h localhost -d ancient_trials -f backend/db/seed.sql
psql -U $DbUser -h localhost -d ancient_trials -c "\dt"
