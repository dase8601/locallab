#!/usr/bin/env bash
# locallab installer — macOS, Linux, and Windows (WSL/Git Bash)
# Usage: curl -fsSL https://raw.githubusercontent.com/dase8601/locallab/main/install.sh | bash
#        bash install.sh --update    (update existing install)

set -e

LOCALLAB_DIR="$HOME/.locallab"
REPO_URL="https://github.com/dase8601/locallab"
REQUIRED_MODELS=("nomic-embed-text" "llama3.1:8b" "qwen2.5:14b")
UPDATE_MODE=false

# Parse flags
for arg in "$@"; do
    case $arg in
        --update) UPDATE_MODE=true ;;
    esac
done

# ── Colors (disabled if not a terminal) ──────────────────────────
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; RESET=''
fi

info()    { echo -e "${BLUE}▸${RESET} $1"; }
success() { echo -e "${GREEN}✓${RESET} $1"; }
warn()    { echo -e "${YELLOW}!${RESET} $1"; }
fatal()   { echo -e "${RED}✗${RESET} $1"; exit 1; }

echo ""
echo -e "${BOLD}  locallab${RESET} — private AI for your files"
echo "  ─────────────────────────────────────"
echo ""

# ── Detect OS ────────────────────────────────────────────────────
OS="unknown"
case "$(uname -s 2>/dev/null)" in
    Darwin*)  OS="macos"   ;;
    Linux*)   OS="linux"   ;;
    MINGW*|MSYS*|CYGWIN*) OS="windows" ;;
esac

# Windows: check if running under WSL
if [ "$OS" = "linux" ] && grep -qi microsoft /proc/version 2>/dev/null; then
    OS="wsl"
fi

info "Detected OS: $OS"

# ── 1. Python 3.10+ ──────────────────────────────────────────────
info "Checking Python..."
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        if $cmd -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo ""
    warn "Python 3.10+ is required."
    case "$OS" in
        macos)   echo "  Install via: brew install python@3.12  or  https://python.org" ;;
        linux|wsl) echo "  Install via: sudo apt update && sudo apt install python3.12 python3.12-venv" ;;
        windows) echo "  Install from: https://python.org/downloads/" ;;
    esac
    echo ""
    fatal "Re-run this installer after installing Python 3.10+."
fi
success "Python found: $($PYTHON --version)"

# ── 2. Ollama ───────────────────────────────────────────────────
info "Checking Ollama..."
if ! command -v ollama &>/dev/null; then
    echo ""
    warn "Ollama is not installed. locallab needs it to run local AI models."
    case "$OS" in
        macos)
            echo -e "  Install Ollama: ${BOLD}https://ollama.com/download${RESET}"
            read -p "  Open ollama.com/download in your browser? [Y/n] " -n 1 -r
            echo ""
            [[ $REPLY =~ ^[Yy]$|^$ ]] && open "https://ollama.com/download" 2>/dev/null || true
            ;;
        linux|wsl)
            echo "  Auto-installing Ollama for Linux..."
            curl -fsSL https://ollama.com/install.sh | sh || fatal "Ollama install failed — visit https://ollama.com"
            ;;
        windows)
            echo -e "  Install Ollama from: ${BOLD}https://ollama.com/download${RESET}"
            ;;
    esac
    # Re-check after potential auto-install
    if ! command -v ollama &>/dev/null; then
        fatal "Re-run this installer after installing Ollama."
    fi
fi
success "Ollama found: $(ollama --version 2>/dev/null | head -1)"

# ── 3. git ──────────────────────────────────────────────────────
info "Checking git..."
if ! command -v git &>/dev/null; then
    case "$OS" in
        macos)   fatal "git required. Install via: xcode-select --install" ;;
        linux|wsl) fatal "git required. Install via: sudo apt install git" ;;
        windows) fatal "git required. Install from: https://git-scm.com/downloads" ;;
        *)       fatal "git is required. Install it and re-run." ;;
    esac
fi
success "git found"

# ── 4. Download / update locallab ────────────────────────────────
if [ "$UPDATE_MODE" = true ] && [ -d "$LOCALLAB_DIR" ]; then
    info "Updating existing locallab install..."
    cd "$LOCALLAB_DIR"
    git pull -q || warn "Could not pull latest — continuing with existing version"
    success "Updated"
elif [ -d "$LOCALLAB_DIR" ] && [ ! "$UPDATE_MODE" = true ]; then
    warn "Existing install found at $LOCALLAB_DIR — use --update to upgrade"
    cd "$LOCALLAB_DIR"
else
    info "Installing locallab to $LOCALLAB_DIR..."
    git clone -q "$REPO_URL" "$LOCALLAB_DIR" || fatal "Clone failed. Check your internet connection."
    success "locallab downloaded"
fi

# ── 5. Python virtual environment ───────────────────────────────
info "Setting up Python environment..."
cd "$LOCALLAB_DIR"
if [ ! -d "venv" ]; then
    $PYTHON -m venv venv || fatal "Failed to create venv — try: $PYTHON -m pip install virtualenv"
fi

# Activate venv — handle both Unix and Windows paths
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    # Git Bash on Windows
    source venv/Scripts/activate
fi

pip install -q --upgrade pip
pip install -q -r requirements.txt
success "Dependencies installed"

# ── 6. Pull Ollama models ────────────────────────────────────────
echo ""
info "Pulling AI models (one-time download, ~15GB total)..."
echo "  You can skip a model and pull it later with: ollama pull <model>"
echo ""

for MODEL in "${REQUIRED_MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "^${MODEL}"; then
        success "Already have: $MODEL"
    else
        info "Pulling $MODEL (this may take a few minutes)..."
        ollama pull "$MODEL" || warn "Could not pull $MODEL — run: ollama pull $MODEL later"
    fi
done

# ── 7. Initialize database ────────────────────────────────────────
info "Initializing database..."
$PYTHON -c "import sys; sys.path.insert(0,'core'); from ingest import init_db; init_db(); print('  DB ready')"
success "Database initialized"

# ── 8. Create launcher ────────────────────────────────────────────
info "Creating 'locallab' launcher..."
LAUNCHER_CONTENT="#!/usr/bin/env bash
cd \"$LOCALLAB_DIR\"
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null
python ui/app.py
"

# Try system bin, fall back to ~/.local/bin
LAUNCHER_INSTALLED=false
for TARGET in "/usr/local/bin/locallab" "$HOME/.local/bin/locallab"; do
    DIR=$(dirname "$TARGET")
    mkdir -p "$DIR" 2>/dev/null || true
    if echo "$LAUNCHER_CONTENT" > "$TARGET" 2>/dev/null; then
        chmod +x "$TARGET"
        LAUNCHER_INSTALLED=true
        LAUNCHER_PATH="$TARGET"
        break
    fi
    # Try with sudo for /usr/local/bin
    if [ "$DIR" = "/usr/local/bin" ]; then
        if echo "$LAUNCHER_CONTENT" | sudo tee "$TARGET" > /dev/null 2>&1; then
            sudo chmod +x "$TARGET"
            LAUNCHER_INSTALLED=true
            LAUNCHER_PATH="$TARGET"
            break
        fi
    fi
done

if [ "$LAUNCHER_INSTALLED" = true ]; then
    success "'locallab' command created at $LAUNCHER_PATH"
    if [[ "$LAUNCHER_PATH" == "$HOME/.local/bin"* ]]; then
        warn "Add to PATH if needed: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
else
    warn "Could not create launcher. Run locallab manually:"
    echo "    cd $LOCALLAB_DIR && source venv/bin/activate && python ui/app.py"
fi

# ── Done ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}  locallab is ready!${RESET}"
echo ""
echo -e "  Start:  ${BOLD}locallab${RESET}  (or: cd $LOCALLAB_DIR && python ui/app.py)"
echo -e "  Open:   ${BOLD}http://localhost:5000${RESET}"
echo -e "  Update: ${BOLD}bash install.sh --update${RESET}"
echo ""
echo "  Drop any PDF, Word doc, or text file into the Files tab."
echo "  Ask questions about your documents."
echo "  Everything stays on your machine — zero cloud."
echo ""
