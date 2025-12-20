# PostgreSQL Integration Setup Guide

## Prerequisites

- [x] Database schema created (`backend/database/schema.sql`)
- [x] Docker Compose file created (`docker-compose.yml`)
- [x] Migration script created (`backend/scripts/migrate_to_postgres.py`)
- [x] Environment variables template (`.env.example`)

---

## Step 1: Install Docker Desktop

### For macOS

**Option A: Using Homebrew**

```bash
brew install --cask docker
```

**Option B: Direct Download**

1. Visit: https://www.docker.com/products/docker-desktop/
2. Download for Mac (choose Apple Silicon or Intel)
3. Install and launch Docker Desktop

**Verify Installation:**

```bash
docker --version
docker-compose --version
```

---

## Step 2: Start PostgreSQL

```bash
# Navigate to project root
cd /Users/yanker/Code/ZenithAlgo

# Copy environment variables
cp .env.example .env

# Start PostgreSQL container
docker-compose up -d postgres

# Check status
docker-compose ps

# View logs
docker-compose logs -f postgres
```

**Expected Output:**

```
Creating zenithalgo-postgres ... done
```

---

## Step 3: Verify Database

```bash
# Connect to database
docker-compose exec postgres psql -U zenith -d zenithalgo

# Inside psql:
\dt  # List tables
\q   # Quit
```

**Expected Tables:**

- backtests
- equity_curves
- trades
- sweep_runs

---

## Step 4: Migrate CSV Data

```bash
# Install Python dependencies
cd backend
uv add psycopg2-binary pandas

# Run migration
uv run python scripts/migrate_to_postgres.py
```

**Expected Output:**

```
Found 18 sweep files to migrate
...
✅ Migration complete! Total records: 460

Found 14 equity files to migrate
...
✅ Equity migration complete!
```

---

## Step 5: Update Go API

```bash
# Add PostgreSQL dependency
cd backend/api
go get github.com/lib/pq
go get github.com/jmoiron/sqlx

# Restart API server
# (Will be done in next phase)
```

---

## Troubleshooting

### Docker not starting

```bash
# Check if Docker Desktop is running
open -a Docker

# Wait for "Docker is running" in menu bar
```

### Port 5432 already in use

```bash
# Check what's using the port
lsof -i :5432

# Kill the process or change port in docker-compose.yml
```

### Connection refused

```bash
# Ensure container is running
docker-compose ps

# Check logs
docker-compose logs postgres

# Restart container
docker-compose restart postgres
```

---

## Quick Reference

```bash
# Start database
docker-compose up -d postgres

# Stop database
docker-compose down

# View logs
docker-compose logs -f postgres

# Connect to database
docker-compose exec postgres psql -U zenith -d zenithalgo

# Backup database
docker-compose exec postgres pg_dump -U zenith zenithalgo > backup.sql

# Restore database
docker-compose exec -T postgres psql -U zenith zenithalgo < backup.sql
```

---

## Next Steps

After successful migration:

1. Update Go API to use PostgreSQL (Phase 1)
2. Update Python backtest to write to PostgreSQL (Phase 2)
3. Test end-to-end workflow
4. Deprecate CSV storage
