import os
import re
import sys
import time
import struct
import argparse

VPK_SIGNATURE = 0x55AA1234
VPK_TERMINATOR = 0xFFFF
EMBEDDED_ARCHIVE = 0x7FFF

CS2_GAME_DIR = "Counter-Strike Global Offensive"
CS2_MAPS_SUFFIX = os.path.join("game", "csgo", "maps")
MAP_PREFIXES = ("de_", "cs_")

class VpkError(Exception):
    pass

class VpkEntry:
    __slots__ = ("path", "archive_index", "offset", "length", "preload")

    def __init__(self, path, archive_index, offset, length, preload):
        self.path = path
        self.archive_index = archive_index
        self.offset = offset
        self.length = length
        self.preload = preload

class Vpk:
    def __init__(self, file_path):
        self.file_path = file_path
        self.archive_base = self._archive_base(file_path)
        self.header_size = 0
        self.tree_size = 0
        self.version = 0
        self.entries = []
        self._parse_header_and_tree()

    @staticmethod
    def _archive_base(file_path):
        directory = os.path.dirname(file_path)
        name = os.path.basename(file_path)
        stem = re.sub(r"\.vpk$", "", name, flags=re.IGNORECASE)
        stem = re.sub(r"_dir$", "", stem, flags=re.IGNORECASE)
        stem = re.sub(r"_\d{3}$", "", stem)
        return os.path.join(directory, stem)

    def _parse_header_and_tree(self):
        with open(self.file_path, "rb") as handle:
            header = handle.read(28)
            if len(header) < 12:
                raise VpkError("file too small to be a VPK")
            signature, version, tree_size = struct.unpack_from("<III", header, 0)
            if signature != VPK_SIGNATURE:
                raise VpkError("bad VPK signature 0x%08X" % signature)
            self.version = version
            self.tree_size = tree_size
            self.header_size = 28 if version == 2 else 12
            if version >= 2:
                handle.seek(0)
                full_header = handle.read(self.header_size)
                tree_size = struct.unpack_from("<I", full_header, 8)[0]
                self.tree_size = tree_size
            handle.seek(self.header_size)
            tree = handle.read(self.tree_size)
            if len(tree) != self.tree_size:
                raise VpkError("truncated VPK tree")
        self.entries = self._walk_tree(tree)

    @staticmethod
    def _read_cstring(buffer, offset):
        end = buffer.find(b"\x00", offset)
        if end < 0:
            raise VpkError("unterminated string in VPK tree")
        return buffer[offset:end].decode("utf-8", "replace"), end + 1

    def _walk_tree(self, tree):
        entries = []
        total = len(tree)
        offset = 0
        while offset < total:
            extension, offset = self._read_cstring(tree, offset)
            if extension == "":
                break
            while offset < total:
                path, offset = self._read_cstring(tree, offset)
                if path == "":
                    break
                while offset < total:
                    name, offset = self._read_cstring(tree, offset)
                    if name == "":
                        break
                    if offset + 18 > total:
                        raise VpkError("truncated VPK entry")
                    _, preload_bytes, archive_index, entry_offset, entry_length, terminator = \
                        struct.unpack_from("<IHHIIH", tree, offset)
                    offset += 18
                    if terminator != VPK_TERMINATOR:
                        raise VpkError("bad VPK entry terminator 0x%04X" % terminator)
                    preload = tree[offset:offset + preload_bytes]
                    offset += preload_bytes
                    full_path = path + "/" + name
                    if extension:
                        full_path += "." + extension
                    entries.append(VpkEntry(full_path, archive_index, entry_offset,
                                            entry_length, preload))
        return entries

    def read_entry(self, entry):
        if entry.preload:
            return entry.preload
        if entry.archive_index == EMBEDDED_ARCHIVE:
            absolute = self.header_size + self.tree_size + entry.offset
            with open(self.file_path, "rb") as handle:
                handle.seek(absolute)
                return handle.read(entry.length)
        archive_path = "%s_%03d.vpk" % (self.archive_base, entry.archive_index)
        if not os.path.isfile(archive_path):
            raise VpkError("missing archive chunk %s" % os.path.basename(archive_path))
        with open(archive_path, "rb") as handle:
            handle.seek(entry.offset)
            return handle.read(entry.length)

    def find_by_extension(self, extension):
        suffix = "." + extension.lower()
        return [e for e in self.entries if e.path.lower().endswith(suffix)]

def read_registry_steam_paths():
    paths = []
    try:
        import winreg
    except ImportError:
        return paths
    probes = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    )
    for hive, key_path, value_name in probes:
        try:
            key = winreg.OpenKey(hive, key_path)
            value, _ = winreg.QueryValueEx(key, value_name)
            winreg.CloseKey(key)
            if value:
                paths.append(value.replace("/", os.sep))
        except OSError:
            continue
    return paths

def read_library_folders(steam_root):
    libraries = []
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    if not os.path.isfile(vdf):
        return libraries
    try:
        with open(vdf, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return libraries
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        libraries.append(match.group(1).replace("\\\\", "\\"))
    return libraries

def default_steam_roots():
    roots = []
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            roots.append(os.path.join(base, "Steam"))
    roots.append(r"C:\Steam")
    for drive in "CDEFGH":
        roots.append(drive + ":\\Steam")
        roots.append(drive + ":\\SteamLibrary")
        roots.append(drive + ":\\Program Files (x86)\\Steam")
    return roots

def candidate_steam_roots(explicit):
    seen = []
    sources = []
    if explicit:
        sources = [explicit]
    else:
        sources = []
        sources.extend(read_registry_steam_paths())
        sources.extend(default_steam_roots())
    for path in sources:
        norm = os.path.normpath(path)
        if norm not in seen:
            seen.append(norm)
    return seen

def maps_dir_variants(base):
    return [
        base,
        os.path.join(base, CS2_MAPS_SUFFIX),
        os.path.join(base, "steamapps", "common", CS2_GAME_DIR, CS2_MAPS_SUFFIX),
        os.path.join(base, "common", CS2_GAME_DIR, CS2_MAPS_SUFFIX),
        os.path.join(base, CS2_GAME_DIR, CS2_MAPS_SUFFIX),
    ]

def looks_like_maps_dir(path):
    if not os.path.isdir(path):
        return False
    if os.path.basename(path).lower() == "maps":
        return True
    try:
        return any(name.lower().endswith(".vpk") for name in os.listdir(path))
    except OSError:
        return False

def resolve_maps_dir(explicit_path):
    if explicit_path:
        target = os.path.normpath(explicit_path)
        for variant in maps_dir_variants(target):
            if looks_like_maps_dir(variant):
                return os.path.abspath(variant)
        raise SystemExit("Could not locate the CS2 maps folder from: %s" % explicit_path)

    tried = []
    for root in candidate_steam_roots(None):
        tried.append(root)
        libraries = [root]
        libraries.extend(read_library_folders(root))
        for library in libraries:
            maps = os.path.join(library, "steamapps", "common", CS2_GAME_DIR, CS2_MAPS_SUFFIX)
            if looks_like_maps_dir(maps):
                return os.path.abspath(maps)
    raise SystemExit("Steam or the CS2 maps folder could not be located. "
                     "Searched:\n  " + "\n  ".join(tried) +
                     "\nUse --path to point at the Steam root, the game folder, or the maps folder.")

def iter_target_vpks(maps_dir):
    results = []
    for name in sorted(os.listdir(maps_dir)):
        if not name.lower().endswith(".vpk"):
            continue
        if not name.startswith(MAP_PREFIXES):
            continue
        full = os.path.join(maps_dir, name)
        if os.path.isfile(full):
            results.append(full)
    return results

def dump_navs(maps_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    targets = iter_target_vpks(maps_dir)
    print("[*] Maps folder : %s" % maps_dir)
    print("[*] Output folder: %s" % output_dir)
    print("[*] Map packages : %d" % len(targets))
    print("-" * 62)

    total_navs = 0
    total_bytes = 0
    failed = []
    started = time.time()

    for index, vpk_path in enumerate(targets, 1):
        name = os.path.basename(vpk_path)
        prefix = "[%d/%d] %s" % (index, len(targets), name)
        try:
            vpk = Vpk(vpk_path)
            navs = vpk.find_by_extension("nav")
        except (VpkError, OSError) as error:
            print("%s -> ERROR: %s" % (prefix, error))
            failed.append(name)
            continue

        if not navs:
            print("%s -> no .nav found" % prefix)
            continue

        for entry in navs:
            try:
                data = vpk.read_entry(entry)
            except (VpkError, OSError) as error:
                print("%s -> ERROR reading %s: %s" % (prefix, entry.path, error))
                failed.append(name)
                continue
            if len(data) != entry.length:
                print("%s -> WARNING: %s short read (%d/%d bytes)"
                      % (prefix, entry.path, len(data), entry.length))
            out_name = os.path.basename(entry.path)
            out_path = os.path.join(output_dir, out_name)
            with open(out_path, "wb") as handle:
                handle.write(data)
            total_navs += 1
            total_bytes += len(data)
            print("%s -> %s (%d bytes) [v%d]" % (prefix, out_name, len(data), vpk.version))

    elapsed = time.time() - started
    print("-" * 62)
    print("[+] Extracted %d .nav file(s), %d bytes total" % (total_navs, total_bytes))
    if failed:
        print("[!] Failed packages: %s" % ", ".join(failed))
    print("[+] Done in %.2fs" % elapsed)
    return 0 if total_navs else 1

def build_parser():
    parser = argparse.ArgumentParser(
        description="Export .nav files from CS2 map VPK packages.")
    parser.add_argument("-p", "--path",
                        help="Steam root, CS2 game folder, or maps folder. "
                             "Auto-detected when omitted.")
    parser.add_argument("-o", "--output",
                        help="Output folder for extracted .nav files. "
                             "Defaults to ./output next to this script.")
    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.abspath(args.output) if args.output else os.path.join(script_dir, "output")
    maps_dir = resolve_maps_dir(args.path)
    return dump_navs(maps_dir, output_dir)


if __name__ == "__main__":
    sys.exit(main())