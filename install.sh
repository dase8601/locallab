#!/usr/bin/env bash
# locallab installer
# Usage: curl -fsSL https://raw.githubusercontent.com/yourusername/locallab/main/install.sh | bash

set -e

LOCALLAB_DIR="$HOME/.locallab"
REPO_URL="https://github.com/yourusername/locallab"  # update when published
REQUIRED_MODELS=("nomic-embed-text" "llama3.1:8b" "qwen2.5:14b")

# ── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}▸${RESET} $1"; }
success() { echo -e "${GREEN}✓${RESET} $1"; }
warn()    { echo -e "${YELLOW}!${RESET} $1"; }
fatal()   { echo -e "${RED}✗${RESET} $1"; exit 1; }

echo ""
echo -e "${BOLD}  locallab${RESET} — private AI for your files"
echo "  ─────────────────────────────────────"
echo ""

# ── 1. Python 3.10+ ──────────────────────────────────────────────
info "Checking Python..."
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        VERSION=$($cmd -c 'import sys; print(sys.version_info[:2])' 2>/dev/null)
        if $cmd -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fatal "Python 3.10+ is required. Install from https://python.org or via: brew install python@3.12"
fi
success "Python found: $($PYTHON --version)"

# ── 2. Ollama ───────────────────────────────────────────────────
info "Checking Ollama..."
if ! command -v ollama &>/dev/null; then
    echo ""
    warn "Ollama is not installed. locallab needs it to run local AI models."
    echo -e "  Install Ollama first: ${BOLD}https://ollama.com/download${RESET}"
    echo ""
    read -p "  Open ollama.com/download in your browser now? [Y/n] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$|^$ ]]; then
        open "https://ollama.com/download" 2>/dev/null || true
    fi
    fatal "Re-run this installer after installing Ollama."
fi
success "Ollama found: $(ollama --version 2>/dev/null | head -1)"

# ── 3. Download locallab ─────────────────────────────────────────
info "Installing locallab to $LOCALLAB_DIR..."
if [ -d "$LOCALLAB_DIR" ]; then
    warn "Existing install found at $LOCALLAB_DIR — updating..."
    cd "$LOCALLAB_DIR"
    git pull -q 2>/dev/null || warn "Could not update — continuing with existing version"
else
    if command -v git &>/dev/null; then
        git clone -q "$REPO_URL" "$LOCALLAB_DIR" 2>/dev/null || {
            # Fallback: download zip if git clone fails (no git or private repo)
            warn "git clone failed — downloading zip..."
            mkdir -p "$LOCALLAB_DIR"
            curl -fsSL "$REPO_URL/archive/main.zip" -o /tmp/locallab.zip
            unzip -q /tmp/locallab.zip -d /tmp/
            cp -r /tmp/locallab-main/. "$LOCALLAB_DIR/"
            rm -f /tmp/locallab.zip
        }
    else
        fatal "git is required. Install via: xcode-select --install"
    fi
fi
success "locallab downloaded"

# ── 4. Python environment ────────────────────────────────────────
info "Setting up Python environment..."
cd "$LOCALLAB_DIR"
if [ ! -d "venv" ]; then
    $PYTHON -m venv venv
fi
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
success "Dependencies installed"

# ── 5. Pull Ollama models ────────────────────────────────────────
echo ""
info "Pulling AI models (this happens once, ~15GB total)..."
echo "  Models needed: ${REQUIRED_MODELS[*]}"
echo "  You can skip a model and add it later with: ollama pull <model>"
echo ""

for MODEL in "${REQUIRED_MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "^${MODEL}"; then
        success "Already have: $MODEL"
    else
        info "Pulling $MODEL..."
        ollama pull "$MODEL" || warn "Could not pull $MODEL — skipping (you can run: ollama pull $MODEL later)"
    fi
done

# ── 6. Initialize database ────────────────────────────────────────
info "Initializing database..."
cd "$LOCALLAB_DIR"
source venv/bin/activate
python -c "import sys; sys.path.insert(0,'core'); from ingest import init_db; init_db(); print('DB ready')"
success "Database initialized"

# ── 7. Create launcher command ────────────────────────────────────
LAUNCHER="/usr/local/bin/locallab"
info "Creating 'locallab' command..."
cat > /tmp/locallab_launcher << LAUNCHER
#!/usr/bin/env bash
cd "$LOCALLAB_DIR"
source venv/bin/activate
python ui/app.py
LAUNCHER
chmod +x /tmp/locallab_launcher
mv /tmp/locallab_launcher "$LAUNCHER" 2>/dev/null || {
    sudo mv /tmp/locallab_launcher "$LAUNCHER" 2>/dev/null || {
        # No sudo — put it in ~/.local/bin
        mkdir -p "$HOME/.local/bin"
        mv /tmp/locallab_launcher "$HOME/.local/bin/locallab"
        warn "Added to ~/.local/bin — add it to your PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
    }
}
success "'locallab' command created"

# ── Done ─────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}  locallab is ready!${RESET}"
echo ""
echo -e "  Run it:   ${BOLD}locallab${RESET}"
echo -e "  Open:     ${BOLD}http://localhost:5000${RESET}"
echo ""
echo "  Drop any PDF, Word doc, or text file into the Files tab."
echo "  Ask questions about your documents."
echo "  Everything stays on your machine."
echo ""
