#!/usr/bin/env bash
# install-services.sh
# Instaluje serwisy systemd dla dab2kodi w trybie --user
# Uruchom jako zwykły użytkownik (nie root): bash install-services.sh

set -euo pipefail

DAB_DIR="$(cd "$(dirname "$0")" && pwd)"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
USERNAME="$(id -un)"

echo "=== dab2kodi — instalacja serwisów systemd (user) ==="
echo "    Katalog projektu : $DAB_DIR"
echo "    systemd user dir : $SYSTEMD_USER_DIR"
echo ""

mkdir -p "$SYSTEMD_USER_DIR"

# ── funkcja instalacji z podmienianiem %h i %i na rzeczywiste wartości ──
install_unit() {
    local src="$DAB_DIR/$1"
    local dst="$SYSTEMD_USER_DIR/$1"
    sed "s|%h|$HOME|g; s|%i|$USERNAME|g" "$src" > "$dst"
    echo "  ✓ zainstalowano: $dst"
}

install_unit welle.service
install_unit dab2kodi.service
install_unit dab2kodi.timer
install_unit dab2kodi-server.service

echo ""
echo "  Przeładowanie konfiguracji systemd..."
systemctl --user daemon-reload

echo "  Włączanie i startowanie serwisów..."
systemctl --user enable --now welle.service
systemctl --user enable --now dab2kodi-server.service
systemctl --user enable --now dab2kodi.timer   # timer zastępuje ręczne dab2kodi.service

# Upewnij się że linger jest włączony (serwisy działają bez zalogowanej sesji)
loginctl enable-linger "$USERNAME" 2>/dev/null && \
    echo "  ✓ loginctl linger włączony dla: $USERNAME" || \
    echo "  [WARN] loginctl enable-linger wymaga uprawnień sudo lub działa tylko z systemd-logind"

echo ""
echo "=== Gotowe! ==="
echo ""
echo "  Przydatne komendy:"
echo "    systemctl --user status welle.service"
echo "    systemctl --user status dab2kodi.service"
echo "    systemctl --user status dab2kodi-server.service"
echo "    systemctl --user list-timers"
echo "    journalctl --user -fu welle.service"
echo "    journalctl --user -fu dab2kodi.service"
echo ""
echo "  HTTP server:"
echo "    http://localhost:8765/              (status + linki)"
echo "    http://localhost:8765/playlist.m3u  (Kodi M3U)"
echo "    http://localhost:8765/epg.xml       (Kodi XMLTV)"
echo ""
echo "  Konfiguracja Kodi — pvr.iptvsimple:"
echo "    M3U URL : http://localhost:8765/playlist.m3u"
echo "    EPG URL : http://localhost:8765/epg.xml"
