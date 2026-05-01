#!/bin/bash
# Claude Usage Widget — Quick Install
# Installs dependencies and sets up autostart

set -e

echo "Claude Usage Desktop Widget — Installer"
echo "========================================="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is required but not found."
    exit 1
fi

# Check/install GTK dependencies
echo "Checking dependencies..."
MISSING=""
python3 -c "import gi; gi.require_version('Gtk', '3.0')" 2>/dev/null || MISSING="python3-gi"
python3 -c "import gi; gi.require_foreign('cairo')" 2>/dev/null || MISSING="$MISSING python3-gi-cairo"

if [ -n "$MISSING" ]; then
    echo "Installing missing packages: $MISSING"
    sudo apt install -y $MISSING
fi

# Install widget
INSTALL_DIR="$HOME/.local/share/claude-usage-widget"
mkdir -p "$INSTALL_DIR"
cp claude-usage-widget.py "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/claude-usage-widget.py"

echo "Installed to: $INSTALL_DIR"

# Autostart
read -p "Add to autostart (launch on login)? [Y/n] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    mkdir -p "$HOME/.config/autostart"
    cat > "$HOME/.config/autostart/claude-usage-widget.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Claude Usage Widget
Comment=Desktop widget showing Claude subscription usage
Exec=python3 $INSTALL_DIR/claude-usage-widget.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Icon=utilities-system-monitor
EOF
    echo "Autostart configured."
fi

echo ""
echo "Done! Launch with:"
echo "  python3 $INSTALL_DIR/claude-usage-widget.py"
echo ""
echo "Click the gear icon to connect your Claude account."
