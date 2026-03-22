#!/usr/bin/env python3
"""
abradab2kodi.py — konwerter AbracaDABra → Kodi pvr.iptvsimple
=============================================================
Czyta pliki EPG z katalogow AbracaDABra i generuje:
  - playlist.m3u   (dla pvr.iptvsimple)
  - epg.xml        (XMLTV dla pvr.iptvsimple)

Użycie:
  python3 abradab2kodi.py [--epg-dir DIR] [--spi-dir DIR] [--out-dir DIR] [--stream-base URL]

Domyślne ścieżki (Linux):
  EPG cache:  ~/.cache/AbracaDABra/EPG/
  SPI data:   ~/Downloads/AbracaDABra/SPI/
  Wyjście:    ~/kodi_dab/

Strumienie:
  Skrypt generuje M3U z placeholderami URL.
  Aby Kodi mogło odtwarzać stacje DAB, potrzebny jest lokalny
  streamer (np. welle-io w trybie HTTP) lub zewnętrzne URL internetowe.
  Ustaw --stream-base na adres swojego serwera,
  np. http://localhost:7272/  (welle-io domyślny port)
  albo zostaw puste — M3U zostanie wygenerowane bez działających linków
  (przydatne do samego EPG i listy kanałów).
"""

import argparse
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


# ──────────────────────────────────────────────
# Znane stacje Polskiego Radia DAB+ (SID → nazwa)
# Uzupełnij lub rozszerz o swoje stacje
# ──────────────────────────────────────────────
# KNOWN_STATIONS jest teraz tylko ostatecznym fallbackiem.
# Prawdziwe nazwy są czytane z ServiceList.json (AbracaDABra) lub /mux.json (welle-cli).
# Możesz dodać tu wpisy dla stacji spoza AbracaDABra lub zdefiniować logo.
KNOWN_STATIONS = {
    # "SID_hex": {"name": "Nazwa", "logo": "plik.png", "group": "Grupa"},
}

# Domyślna lokalizacja ServiceList.json (Qt config AbracaDABra)
_SERVICE_LIST_PATHS = [
    Path.home() / ".config/AbracaDABra/ServiceList.json",
    Path.home() / "AppData/Roaming/AbracaDABra/ServiceList.json",   # Windows
    Path.home() / "Library/Preferences/AbracaDABra/ServiceList.json",  # macOS
]


def parse_duration(iso_dur: str) -> int:
    """Konwertuje ISO 8601 duration (PT1H30M0S) na sekundy."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_dur)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


def parse_radiodns_time(t: str) -> datetime:
    """Parsuje czas w formacie 2026-03-22T00:00:00.000+01:00 → datetime (UTC)."""
    # Python 3.6 nie obsługuje %z z kolumną — czyścimy ręcznie
    t_clean = re.sub(r'\.(\d+)', '', t)  # usuń milisekundy
    # Obsłuż strefę czasową
    tz_match = re.search(r'([+-]\d{2}:\d{2})$', t_clean)
    if tz_match:
        tz_str = tz_match.group(1)
        t_base = t_clean[: -len(tz_str)]
        sign = 1 if tz_str[0] == '+' else -1
        hh, mm = int(tz_str[1:3]), int(tz_str[4:6])
        tz_offset = timezone(timedelta(hours=sign * hh, minutes=sign * mm))
        dt = datetime.strptime(t_base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tz_offset)
    else:
        dt = datetime.fromisoformat(t_clean)
    return dt.astimezone(timezone.utc)


def xmltv_time(dt: datetime) -> str:
    """Formatuje datetime do XMLTV: 20260322010000 +0000"""
    return dt.strftime("%Y%m%d%H%M%S +0000")


def extract_sid(scope_id: str) -> str:
    """
    Z 'dab:3e2.3183.3211.0' wyciąga SID '3211' (hex).
    Format: dab:ECC.EnsID.SID.SCIdS
    """
    parts = scope_id.split(".")
    if len(parts) >= 3:
        return parts[2].lower()
    return ""


def sid_to_tvgid(sid: str) -> str:
    return f"dab.{sid}"


def collect_epg_files(epg_dir: Path):
    """
    Zwraca listę plików EPG PI XML z podanego katalogu.
    Pliki mają nazwy: 20260322_e23211.0_PI.xml
    Zwraca: [(filepath, sid_hex, date_str), ...]
    """
    result = []
    if not epg_dir.exists():
        return result
    pattern = re.compile(r"(\d{8})_(e[0-9a-f]+)\.(\d+)_PI\.xml", re.I)
    for f in epg_dir.glob("*.xml"):
        m = pattern.match(f.name)
        if m:
            date_str = m.group(1)
            sid_hex = m.group(2)[1:]  # usuń prefix 'e'
            result.append((f, sid_hex, date_str))
    return result


def parse_epg_file(filepath) -> list:
    """
    Parsuje RadioEPG PI XML i zwraca listę programów:
    [{"sid": str, "start": datetime, "stop": datetime, "name": str, "desc": str}, ...]
    """
    programmes = []
    try:
        if isinstance(filepath, (str, Path)):
            tree = ET.parse(str(filepath))
            root = tree.getroot()
        else:
            # bytes/string przekazane bezpośrednio
            root = ET.fromstring(filepath)

        # Znajdź serviceScope → SID
        sid = ""
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag == "serviceScope":
                sid = extract_sid(el.get("id", ""))
                break

        # Parsuj programy
        for el in root.iter():
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag != "programme":
                continue

            prog = {"sid": sid, "start": None, "stop": None, "name": "", "desc": ""}

            for child in el:
                ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

                if ctag == "longName" and not prog["name"]:
                    prog["name"] = (child.text or "").strip()
                elif ctag == "mediumName" and not prog["name"]:
                    prog["name"] = (child.text or "").strip()

                elif ctag == "location":
                    for t in child:
                        ttag = t.tag.split("}")[-1] if "}" in t.tag else t.tag
                        if ttag == "time":
                            raw_time = t.get("time", "")
                            dur_str = t.get("duration", "PT0S")
                            if raw_time:
                                try:
                                    start = parse_radiodns_time(raw_time)
                                    dur_sec = parse_duration(dur_str)
                                    prog["start"] = start
                                    prog["stop"] = start + timedelta(seconds=dur_sec)
                                except Exception:
                                    pass

                elif ctag == "mediaDescription":
                    for d in child:
                        dtag = d.tag.split("}")[-1] if "}" in d.tag else d.tag
                        if dtag == "shortDescription" and not prog["desc"]:
                            prog["desc"] = (d.text or "").strip()

            if prog["start"] and prog["name"]:
                programmes.append(prog)

    except Exception as e:
        print(f"  [WARN] Błąd parsowania {filepath}: {e}", file=sys.stderr)

    return programmes


def load_all_programmes(epg_dir: Path) -> dict:
    """
    Wczytuje wszystkie pliki EPG.
    Zwraca: {sid_hex: [programmes...]}
    """
    all_files = collect_epg_files(epg_dir)
    if not all_files:
        print(f"  [WARN] Brak plików EPG w: {epg_dir}", file=sys.stderr)
        return {}

    by_sid = {}
    seen = set()  # deduplikacja (sid+start+name)

    for filepath, sid_hex, date_str in sorted(all_files):
        progs = parse_epg_file(filepath)
        for p in progs:
            sid = p["sid"] or sid_hex  # fallback na sid z nazwy pliku
            key = (sid, p["start"], p["name"])
            if key in seen:
                continue
            seen.add(key)
            by_sid.setdefault(sid, []).append(p)

    # Sortuj każdą listę po czasie
    for sid in by_sid:
        by_sid[sid].sort(key=lambda x: x["start"])

    return by_sid



def read_service_list(service_list_path: str = "") -> dict:
    """
    Czyta ServiceList.json z AbracaDABra — zawiera WSZYSTKIE stacje
    odebrane kiedykolwiek przez aplikację, z prawdziwymi nazwami.

    Format: lista obiektów z polami:
      SID        (int, dziesiętnie, np. 14823953 = 0xE23211)
      Label      (str, pełna nazwa, np. "PR Jedynka")
      ShortLabel (str)
      Ensembles  (lista z Label = nazwa multipleksu)

    Zwraca: {sid_hex: {"name": str, "group": str}}
    """
    import json as _json

    # Szukaj pliku — najpierw podana ścieżka, potem domyślne lokalizacje
    candidates = []
    if service_list_path:
        candidates.append(Path(service_list_path))
    candidates.extend(_SERVICE_LIST_PATHS)

    path = None
    for c in candidates:
        if c.exists():
            path = c
            break

    if not path:
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as e:
        print(f"  [WARN] Błąd czytania {path}: {e}", file=sys.stderr)
        return {}

    stations = {}
    for entry in data:
        sid_dec = entry.get("SID")
        label   = (entry.get("Label") or entry.get("ShortLabel") or "").strip()
        if not sid_dec or not label:
            continue

        # Konwertuj SID dziesiętny → hex (tylko ostatnie 4 cyfry hex)
        sid_hex = format(int(sid_dec), "x").lower()
        # AbracaDABra podaje pełny SID np. e23211 — bierzemy ostatnie 4 znaki
        if len(sid_hex) > 4:
            sid_hex = sid_hex[-4:]

        # Nazwa multipleksu (ensemble) jako grupa kanałów
        ensembles = entry.get("Ensembles", [])
        group = ensembles[0].get("Label", "DAB+") if ensembles else "DAB+"

        stations[sid_hex] = {"name": label, "group": group}

    print(f"  ✓ ServiceList.json: {len(stations)} stacji z '{path}'")
    return stations

def fetch_mux_json(stream_base: str) -> dict:
    """
    Pobiera /mux.json z welle-cli — WSZYSTKIE stacje z prawdziwymi nazwami, na żywo.
    To jest najbardziej wiarygodne źródło listy stacji, niezależne od EPG.
    Zwraca pusty słownik jeśli welle-cli nie jest dostępne.
    """
    if not stream_base:
        return {}
    import urllib.request
    import json as _json
    url = stream_base.rstrip("/") + "/mux.json"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = _json.loads(resp.read().decode())
        stations = {}
        services = data.get("services", [])
        ensemble = data.get("ensemble", {}).get("label", "DAB+")
        for svc in services:
            raw_sid = str(svc.get("sid", ""))
            label   = svc.get("label", "").strip()
            if raw_sid.startswith(("0x", "0X")):
                sid = raw_sid[2:].lower().lstrip("0") or "0"
            else:
                try:
                    sid = format(int(raw_sid), "x").lstrip("0") or "0"
                except ValueError:
                    sid = raw_sid.lower()
            if sid and label:
                stations[sid] = {"name": label, "ensemble": ensemble}
        print(f"  ✓ /mux.json: {len(stations)} stacji z multipleksu '{ensemble}'")
        return stations
    except Exception as e:
        print(f"  [INFO] /mux.json niedostępne ({e}) — używam plików lokalnych",
              file=__import__("sys").stderr)
        return {}


def find_logo_in_spi(name: str, logos_dir: Path) -> str:
    """
    Fuzzy match nazwy stacji do pliku PNG w katalogu logos.
    Zwraca file:// URI lub pusty string.
    """
    import unicodedata
    if not logos_dir or not logos_dir.exists():
        return ""

    def norm(s):
        s = unicodedata.normalize("NFKD", s.lower())
        return re.sub(r"[^a-z0-9]", "", s)

    name_n = norm(name)
    best, best_score = None, 0
    for png in logos_dir.glob("*.png"):
        stem = norm(png.stem)
        if not stem:
            continue
        if stem in name_n or name_n[:len(stem)] == stem:
            score = len(stem)
        else:
            score = sum(a == b for a, b in zip(stem, name_n))
            if score < 2:
                score = 0
        if score > best_score:
            best_score, best = score, png
    return best.as_uri() if best and best_score >= 2 else ""


def discover_stations(programmes_by_sid: dict, spi_dir: Path,
                      mux_stations: dict, service_list: dict,
                      stream_base: str = "", out_dir: Path = None) -> dict:
    """
    Buduje słownik stacji {sid_hex: {name, group, logo}}.

    Priorytet źródeł nazw:
      1. ServiceList.json (AbracaDABra) — wszystkie odebrane stacje, świeże nazwy
      2. /mux.json (welle-cli)          — stacje aktualnie w powietrzu
      3. EPG PI.xml / EHB.xml           — stacje nadające EPG
      4. KNOWN_STATIONS                 — ostateczny fallback
      5. "DAB {SID}"

    Priorytet źródeł logo:
      1. {stream_base}/slide/0xSID        — obraz SLS z welle-cli (logo stacji na żywo)
      2. PNG z SPI skopiowane do out_dir/logos/ (fuzzy match do nazwy)
      3. brak logo
    """
    # Skopiuj PNG z SPI do out_dir/logos/ (Kodi wymaga file:// lub http://)
    logos_dir = None
    if spi_dir and spi_dir.exists() and out_dir:
        logos_dir = out_dir / "logos"
        logos_dir.mkdir(exist_ok=True)
        import shutil
        for png in spi_dir.rglob("*.png"):
            dest = logos_dir / png.name
            if not dest.exists():
                shutil.copy2(png, dest)

    stations = {}
    all_sids = set()
    all_sids.update(service_list.keys())
    all_sids.update(mux_stations.keys())
    all_sids.update(KNOWN_STATIONS.keys())
    all_sids.update(programmes_by_sid.keys())

    for sid in all_sids:
        # Nazwa stacji
        if sid in service_list:
            name  = service_list[sid]["name"]
            group = service_list[sid].get("group", "DAB+")
        elif sid in mux_stations:
            name  = mux_stations[sid]["name"]
            group = mux_stations[sid].get("ensemble", "DAB+")
        elif sid in KNOWN_STATIONS:
            name  = KNOWN_STATIONS[sid]["name"]
            group = KNOWN_STATIONS[sid].get("group", "DAB+")
        else:
            name  = f"DAB {sid.upper()}"
            group = "DAB+"

        # Logo stacji
        if stream_base:
            # welle-cli: /slide/0xSID serwuje aktualny obraz SLS (logo nadawane przez DAB)
            logo = f"{stream_base.rstrip('/')}/slide/0x{sid}"
        elif logos_dir:
            logo = find_logo_in_spi(name, logos_dir)
        else:
            logo = ""

        stations[sid] = {"name": name, "group": group, "logo": logo}

    return stations

def generate_m3u(stations: dict, programmes_by_sid: dict, stream_base: str, out_file: Path, epg_xml_path: Path):
    """Generuje plik M3U dla pvr.iptvsimple."""
    epg_url = epg_xml_path.as_uri()

    lines = [f'#EXTM3U x-tvg-url="{epg_url}"\n']

    for sid, info in sorted(stations.items(), key=lambda x: x[1]["name"]):
        tvg_id = sid_to_tvgid(sid)
        name = info["name"]
        group = info["group"]
        logo = info.get("logo", "")
        progs = programmes_by_sid.get(sid, [])
        count = len(progs)

        # Strumień URL — placeholder lub z welle-io
        if stream_base:
            # welle-io http-api: GET /mp3?sid=0x3211
            stream_url = f"{stream_base.rstrip('/')}/mp3/0x{sid}"
        else:
            # Placeholder — bez działającego URL Kodi nie odtworzy dźwięku
            # ale EPG i lista kanałów będą działać
            stream_url = f"dab://{sid}"

        logo_attr = f' tvg-logo="{logo}"' if logo else ""
        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}"{logo_attr}'
            f' group-title="{group}" radio="true",{name}\n'
        )
        lines.append(f"{stream_url}\n")
        lines.append("\n")

    out_file.write_text("".join(lines), encoding="utf-8")
    print(f"  ✓ M3U: {out_file}  ({len(stations)} kanałów)")


def generate_xmltv(stations: dict, programmes_by_sid: dict, out_file: Path):
    """Generuje plik XMLTV EPG dla pvr.iptvsimple."""
    root = ET.Element("tv")
    root.set("generator-info-name", "abradab2kodi")
    root.set("source-info-name", "AbracaDABra DAB+ EPG")

    # <channel> elementy
    for sid, info in sorted(stations.items(), key=lambda x: x[1]["name"]):
        tvg_id = sid_to_tvgid(sid)
        ch = ET.SubElement(root, "channel", id=tvg_id)
        dn = ET.SubElement(ch, "display-name", lang="pl")
        dn.text = info["name"]
        if info.get("logo"):
            ET.SubElement(ch, "icon", src=info["logo"])

    # <programme> elementy
    total = 0
    for sid, progs in programmes_by_sid.items():
        tvg_id = sid_to_tvgid(sid)
        for p in progs:
            if not p["start"] or not p["stop"]:
                continue
            prog_el = ET.SubElement(
                root,
                "programme",
                start=xmltv_time(p["start"]),
                stop=xmltv_time(p["stop"]),
                channel=tvg_id,
            )
            title = ET.SubElement(prog_el, "title", lang="pl")
            title.text = p["name"]
            if p.get("desc"):
                desc = ET.SubElement(prog_el, "desc", lang="pl")
                desc.text = p["desc"]
            total += 1

    # Ladny zapis z wcięciami
    _indent(root)
    tree = ET.ElementTree(root)
    ET.register_namespace("", "")
    with open(out_file, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        f.write(b'<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')
        tree.write(f, encoding="utf-8", xml_declaration=False)

    print(f"  ✓ XMLTV EPG: {out_file}  ({total} programów, {len(programmes_by_sid)} kanałów)")


def _indent(elem, level=0):
    """Dodaje wcięcia do XML (in-place)."""
    pad = "\n" + "  " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = pad
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = pad
    if not level:
        elem.tail = "\n"


def print_summary(stations, programmes_by_sid):
    print("\n  Znalezione kanały:")
    for sid, info in sorted(stations.items(), key=lambda x: x[1]["name"]):
        count = len(programmes_by_sid.get(sid, []))
        days = set()
        for p in programmes_by_sid.get(sid, []):
            if p["start"]:
                days.add(p["start"].strftime("%Y-%m-%d"))
        if count:
            days_str = f"{len(days)} dni EPG"
        else:
            days_str = "⚠ brak EPG"
        print(f"    [{sid}] {info['name']:30s} — {count:3d} progr. ({days_str})")


# ──────────────────────────────────────────────────────
# TRYB ZIP (do użycia bezpośrednio z pobranego archiwum)
# ──────────────────────────────────────────────────────

def load_from_zips(abra_zip: str, apps_zip: str) -> tuple:
    """Wczytuje EPG z plików ZIP (AbracaDABra.zip + userApps.zip)."""
    programmes_by_sid = {}
    seen = set()

    # AbracaDABra.zip → EPG/
    print(f"  Czytam EPG z: {abra_zip}")
    with zipfile.ZipFile(abra_zip) as z:
        pi_files = [f for f in z.namelist() if re.search(r"EPG/.*_PI\.xml$", f)]
        print(f"  Znaleziono {len(pi_files)} plików EPG PI")
        for fname in pi_files:
            m = re.search(r"(\d{8})_(e[0-9a-f]+)\.(\d+)_PI\.xml", fname, re.I)
            if not m:
                continue
            sid_hex = m.group(2)[1:]  # bez 'e'
            data = z.read(fname)
            progs = parse_epg_file(data)
            for p in progs:
                sid = p["sid"] or sid_hex
                key = (sid, p["start"], p["name"])
                if key not in seen:
                    seen.add(key)
                    programmes_by_sid.setdefault(sid, []).append(p)

    # userApps.zip → SPI/*.EHB.xml (dodatkowe EPG)
    if apps_zip and os.path.exists(apps_zip):
        print(f"  Czytam SPI EPG z: {apps_zip}")
        with zipfile.ZipFile(apps_zip) as z:
            ehb_files = [f for f in z.namelist() if f.endswith(".EHB.xml")]
            print(f"  Znaleziono {len(ehb_files)} plików SPI EHB")
            for fname in ehb_files:
                data = z.read(fname)
                progs = parse_epg_file(data)
                for p in progs:
                    if not p["sid"]:
                        continue
                    key = (p["sid"], p["start"], p["name"])
                    if key not in seen:
                        seen.add(key)
                        programmes_by_sid.setdefault(p["sid"], []).append(p)

    # Sortuj
    for sid in programmes_by_sid:
        programmes_by_sid[sid].sort(key=lambda x: x["start"])

    return programmes_by_sid


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AbracaDABra → Kodi pvr.iptvsimple (M3U + XMLTV)"
    )
    parser.add_argument(
        "--epg-dir",
        default=str(Path.home() / ".cache/AbracaDABra/EPG"),
        help="Katalog z plikami EPG AbracaDABra (domyślnie: ~/.cache/AbracaDABra/EPG/)",
    )
    parser.add_argument(
        "--spi-dir",
        default=str(Path.home() / "Downloads/AbracaDABra/SPI"),
        help="Katalog z danymi SPI (domyślnie: ~/Downloads/AbracaDABra/SPI/)",
    )
    parser.add_argument(
        "--abra-zip",
        default="",
        help="Ścieżka do AbracaDABra.zip (tryb ZIP zamiast katalogów)",
    )
    parser.add_argument(
        "--apps-zip",
        default="",
        help="Ścieżka do userApps.zip (opcjonalny dodatkowy EPG z SPI)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path.home() / "kodi_dab"),
        help="Katalog wyjściowy (domyślnie: ~/kodi_dab/)",
    )
    parser.add_argument(
        "--service-list",
        default="",
        help=(
            "Ścieżka do ServiceList.json AbracaDABra\n"
            f"  Domyślnie szukana w: ~/.config/AbracaDABra/ServiceList.json"
        ),
    )
    parser.add_argument(
        "--stream-base",
        default="",
        help=(
            "Bazowy URL serwera audio, np. http://localhost:7272\n"
            "  welle-io: http://localhost:7272\n"
            "  Icecast:  http://localhost:8000\n"
            "  Puste = placeholder URL (EPG działa, audio nie)"
        ),
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m3u_file = out_dir / "playlist.m3u"
    epg_file = out_dir / "epg.xml"

    print("\n=== AbracaDABra → Kodi converter ===\n")

    # 1. Czytaj ServiceList.json z AbracaDABra (najbardziej kompletne źródło)
    service_list = read_service_list(args.service_list)

    # 2. Pobierz listę stacji z welle-cli /mux.json (aktualne stacje na żywo)
    mux_stations = fetch_mux_json(args.stream_base)

    # 3. Wczytaj EPG z plików AbracaDABra
    if args.abra_zip:
        programmes_by_sid = load_from_zips(args.abra_zip, args.apps_zip)
    else:
        epg_dir = Path(args.epg_dir)
        print(f"  Czytam EPG z katalogu: {epg_dir}")
        programmes_by_sid = load_all_programmes(epg_dir)


    if not programmes_by_sid and not mux_stations and not service_list:
        print("\n  [BŁĄD] Brak danych EPG i brak odpowiedzi z /mux.json.", file=sys.stderr)
        print("  Uruchom welle-cli z --stream-base lub sprawdź ścieżki EPG.", file=sys.stderr)
        sys.exit(1)

    if not programmes_by_sid:
        print("  [INFO] Brak plików EPG — lista stacji pochodzi wyłącznie z /mux.json")

    # 4. Połącz źródła stacji
    spi_dir = Path(args.spi_dir)
    stations = discover_stations(programmes_by_sid, spi_dir, mux_stations, service_list,
                                  args.stream_base, out_dir)

    print_summary(stations, programmes_by_sid)

    print("\n  Generuję pliki wyjściowe...")
    generate_m3u(stations, programmes_by_sid, args.stream_base, m3u_file, epg_file)
    generate_xmltv(stations, programmes_by_sid, epg_file)

    print(f"""
  ── Konfiguracja Kodi pvr.iptvsimple ──
  M3U:  {m3u_file}
  EPG:  {epg_file}

  W Kodi: Addony → PVR IPTV Simple Client → Konfiguruj
    Zakładka "Ogólne":
      Lokalizacja M3U: Lokalna ścieżka
      Plik M3U:        {m3u_file}
    Zakładka "EPG":
      Lokalizacja XMLTV: Lokalna ścieżka
      Plik XMLTV:        {epg_file}

  ── Strumienie audio ──
""")

    if args.stream_base:
        print(f"  Strumienie → {args.stream_base.rstrip('/')}/mp3/0x<SID>")
        print("  (wymaga uruchomionego welle-io lub podobnego)")
    else:
        print("  UWAGA: Brak --stream-base — strumienie mają placeholder URL.")
        print("  Kodi nie będzie odtwarzać audio dopóki nie ustawisz URL.")
        print("  Dla welle-io uruchom: welle-io --http-port 7272 --device rtlsdr")
        print("  a potem: python3 abradab2kodi.py --stream-base http://localhost:7272")

    print()


if __name__ == "__main__":
    main()
