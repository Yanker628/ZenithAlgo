# Docker Installation Guide for macOS

## Quick Installation

### Option 1: Homebrew (Recommended)

```bash
# Install Docker Desktop via Homebrew
brew install --cask docker

# Or download directly from:
# https://docs.docker.com/desktop/install/mac-install/
```

### Option 2: Direct Download

1. Visit: https://www.docker.com/products/docker-desktop/
2. Click "Download for Mac" (Choose Apple Silicon if M1/M2/M3)
3. Open the downloaded `.dmg` file
4. Drag Docker to Applications folder
5. Launch Docker Desktop from Applications

---

## Installation Steps (Manual)

Since brew is not detecting Docker, please:

1. **Download Docker Desktop**:

   - Apple Silicon (M1/M2/M3): [Download Link](https://desktop.docker.com/mac/main/arm64/Docker.dmg)
   - Intel Mac: [Download Link](https://desktop.docker.com/mac/main/amd64/Docker.dmg)

2. **Install**:

   ```bash
   # After downloading
   open ~/Downloads/Docker.dmg

   # Drag Docker to Applications
   # Then launch Docker from Applications folder
   ```

3. **Verify Installation**:

   ```bash
   docker --version
   docker-compose --version
   ```

4. **Start Docker**:
   - Open "Docker Desktop" from Applications
   - Wait for it to start (shows "Docker is running" in menu bar)

---

## After Docker is Installed

Return here and run:

```bash
# Start PostgreSQL
docker-compose up -d postgres

# Check status
docker-compose ps

# View logs
docker-compose logs postgres
```

---

## Troubleshooting

**Issue**: Command not found after install
**Solution**:

```bash
# Restart terminal or run:
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
```

**Issue**: Docker Desktop won't start
**Solution**:

- Ensure you have sufficient disk space (at least 10GB free)
- Check System Preferences → Security & Privacy for permissions
- Restart your Mac
