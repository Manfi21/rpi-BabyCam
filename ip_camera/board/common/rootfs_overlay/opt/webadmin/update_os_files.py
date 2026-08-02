#!/usr/bin/env python3
"""
update_os_files.py

Lightweight OTA for the case where a newer BabyCamOS release only adds
a handful of new files (e.g. a new library) rather than
changing the base build. Downloads the full release image (as published to
GitHub Releases), mounts its boot/root partitions read-only via loop
devices, and copies over files that don't yet exist on this device.

Existing files are only touched in two cases:
* managed init scripts (etc/init.d/*) are ALWAYS overwritten, so a new
  release can ship changes to existing init scripts instead of ignoring them
* mediamtx.yml is written as a .new file next to the live config so the
  user can review and merge changes manually

Everything else on the device is left alone, so it can't clobber on-device
state (wifi config, mediamtx.yml, saved audio settings, etc.) or corrupt a
binary that's currently running. If nothing is missing, nothing happens.

This is deliberately not a full image flash: writing the whole image over
the live, mounted root block device while the system runs from it is what
this script avoids - only individual files are added through the normal
filesystem, which is safe on a live system.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

REPO_USER = "Manfi21"
REPO_NAME = "rpi-BabyCam"
API_URL = f"https://api.github.com/repos/{REPO_USER}/{REPO_NAME}/releases/latest"
VERSION_FILE = "/etc/babycam-version"

BOOT_MOUNT = "/mnt/ota_boot"
ROOT_MOUNT = "/mnt/ota_root"

# Board model substring (from /proc/device-tree/model) -> release asset suffix,
# matching the mapping in build_all.sh.
BOARD_SUFFIXES = [
    ("Raspberry Pi 4", "rpi4"),
    ("Raspberry Pi 3", "rpi3"),
    ("Raspberry Pi Zero 2", "rpizero2w"),
]

# Device-specific state that must never be overwritten by a release image,
# even if it happens to differ.
EXCLUDE_PATHS = {
    "etc/hostname",
    "etc/wpa_supplicant.conf",
    "etc/babycam-version",
    "root/auth_users.txt",
    "opt/webadmin/stream_postfix.txt",
    "opt/webadmin/audio_config.json",
}

MERGE_PATHS = {
    "root/mediamtx.yml",
}

# Files under these path prefixes are always copied from the release image,
# overwriting whatever is currently on the device.
ALWAYS_OVERWRITE_PREFIXES = (
    "etc/init.d/",
)

REQUIRED_FREE_MB = 500  # tar.gz + extracted .img, with headroom

def run_command(command, timeout=5):
    try:
        result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, timeout=timeout)
        return result.decode('utf-8', errors='ignore').strip()
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8', errors='ignore').strip()
    except FileNotFoundError:
        return "CMD not found"
    except subprocess.TimeoutExpired:
        return "CMD timeout"
    except Exception as e:
        return str(e)

def run(cmd, check=True):
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if check and result.returncode != 0:
        if result.stderr.strip():
            print(result.stderr.strip())
        raise RuntimeError(f"Command failed ({result.returncode}): {cmd}")
    return result.stdout.strip()


def detect_board_suffix():
    try:
        with open("/proc/device-tree/model", "rb") as f:
            model = f.read().decode("utf-8", errors="ignore").strip("\x00").strip()
    except Exception as e:
        raise RuntimeError(f"Could not read board model: {e}")

    for needle, suffix in BOARD_SUFFIXES:
        if needle in model:
            print(f"Detected board: {model} -> {suffix}")
            return suffix

    raise RuntimeError(f"Unrecognized board model: '{model}'")


def fetch_release_asset(suffix):
    print("Fetching latest release info...")
    req = urllib.request.Request(API_URL, headers={"User-Agent": "babycam-updater"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)

    tag = data.get("tag_name")
    if not tag:
        raise RuntimeError("Could not determine latest release tag")

    asset_url = None
    asset_name = None
    for asset in data.get("assets", []):
        if asset["name"].endswith(f"_{suffix}.tar.gz"):
            asset_url = asset["browser_download_url"]
            asset_name = asset["name"]
            break

    if not asset_url:
        raise RuntimeError(f"No release asset ending in '_{suffix}.tar.gz' found for {tag}")

    print(f"Latest release: {tag} ({asset_name})")
    return tag, asset_url


def check_free_space(path):
    free_mb = shutil.disk_usage(path).free / (1024 * 1024)
    print(f"Free space on {path}: {free_mb:.0f} MB")
    if free_mb < REQUIRED_FREE_MB:
        raise RuntimeError(
            f"Not enough free space on {path} "
            f"({free_mb:.0f} MB free, need at least {REQUIRED_FREE_MB} MB)"
        )


def download(url, dest):
    print(f"Downloading {url} ...")
    run(f"wget -qO {dest} {url}")


def extract_image(tar_path, tmp_dir):
    print("Extracting image...")
    with tarfile.open(tar_path) as tf:
        img_members = [m for m in tf.getmembers() if m.name.endswith(".img")]
        if not img_members:
            raise RuntimeError("No .img file found inside release tarball")

        if hasattr(tarfile, 'data_filter'):
            tf.extract(img_members[0], tmp_dir, filter='data')
        else:
            tf.extract(img_members[0], tmp_dir)

        return os.path.join(tmp_dir, img_members[0].name)


def read_mbr_partitions(image_path):
    """Reads start offset + size (bytes) of each primary partition from the MBR."""
    with open(image_path, "rb") as f:
        mbr = f.read(512)

    partitions = []
    for i in range(4):
        entry = mbr[446 + i * 16: 446 + (i + 1) * 16]
        part_type = entry[4]
        if part_type == 0:
            continue
        lba_start = int.from_bytes(entry[8:12], "little")
        num_sectors = int.from_bytes(entry[12:16], "little")
        partitions.append({"offset": lba_start * 512, "size": num_sectors * 512})
    return partitions


def losetup_attach(image_path, offset):
    for i in range(20, 40):
        dev = f"/dev/loop{i}"
        if not os.path.exists(dev):
            run(f"mknod {dev} b 7 {i}")
        probe = subprocess.run(f"losetup {dev}", shell=True, capture_output=True, text=True)
        if probe.returncode != 0 or not probe.stdout.strip():
            run(f"losetup -o {offset} {dev} {image_path}")
            return dev
    raise RuntimeError("No free loop device found")


def losetup_detach(dev):
    subprocess.run(f"losetup -d {dev}", shell=True, capture_output=True)


def sync_missing_files(src_root, dst_root, prefix):
    """Copies new files and overwrites managed files (init scripts).

    Returns (copied, overwritten): number of files newly added and number of
    existing files that were replaced.
    """
    copied = 0
    overwritten = 0
    for dirpath, _dirnames, filenames in os.walk(src_root):
        rel_dir = os.path.relpath(dirpath, src_root)
        for name in filenames:
            rel_path = name if rel_dir == "." else os.path.join(rel_dir, name)
            rel_path = os.path.normpath(rel_path)
            exclude_key = os.path.normpath(os.path.join(prefix, rel_path)).lstrip("/")

            if exclude_key in EXCLUDE_PATHS:
                continue

            src_file = os.path.join(dirpath, name)
            dst_file = os.path.join(dst_root, rel_path)

            if os.path.lexists(dst_file):
                if exclude_key in MERGE_PATHS:
                    dst_new = dst_file + ".new"
                    shutil.copy2(src_file, dst_new)
                    print(f"  ~ Wrote updated config to /{exclude_key}.new")

                    try:
                        compare_and_print_config_changes(dst_file, dst_new)
                    except Exception as e:
                        print(f"    -> Could not generate diff: {e}")

                    continue

                if any(exclude_key.startswith(p) for p in ALWAYS_OVERWRITE_PREFIXES):
                    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                    if os.path.islink(src_file):
                        if os.path.lexists(dst_file):
                            os.unlink(dst_file)
                        os.symlink(os.readlink(src_file), dst_file)
                    else:
                        shutil.copy2(src_file, dst_file)
                    print(f"  ! /{exclude_key}")
                    overwritten += 1

                continue

            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            if os.path.islink(src_file):
                os.symlink(os.readlink(src_file), dst_file)
            else:
                shutil.copy2(src_file, dst_file)
            print(f"  + /{exclude_key}")
            copied += 1
    return copied, overwritten



def update_version_file(new_version):
    if not os.path.exists(VERSION_FILE):
        return
    with open(VERSION_FILE) as f:
        content = f.read()
    content = re.sub(r"^VERSION=.*$", f"VERSION={new_version}", content, count=1, flags=re.MULTILINE)
    with open(VERSION_FILE, "w") as f:
        f.write(content)
    print(f"Updated {VERSION_FILE}: VERSION={new_version}")

def parse_simple_yaml(file_path):
    flat_dict = {}
    path_stack = []

    if not os.path.exists(file_path):
        return flat_dict

    with open(file_path, 'r') as f:
        for line in f:
            # Kommentare und Leerzeilen überspringen
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # Einrückung ermitteln (2 Leerzeichen pro Ebene)
            indent = len(line) - len(line.lstrip(' '))
            level = indent // 2

            if ':' in stripped:
                parts = stripped.split(':', 1)
                key = parts[0].strip()
                val = parts[1].strip().strip('"\'')

                # Stack auf aktuelle Ebene kürzen
                path_stack = path_stack[:level]
                path_stack.append(key)

                # Wenn es einen Wert gibt, speichern
                if val:
                    full_key = '.'.join(path_stack)
                    flat_dict[full_key] = val

    return flat_dict

def compare_and_print_config_changes(old_file, new_file):
    old_cfg = parse_simple_yaml(old_file)
    new_cfg = parse_simple_yaml(new_file)

    added_keys = set(new_cfg.keys()) - set(old_cfg.keys())
    changed_keys = {k for k in old_cfg.keys() & new_cfg.keys() if old_cfg[k] != new_cfg[k]}

    if added_keys or changed_keys:
        print("--- Configuration Changes ---")
        if added_keys:
            print("-> New added:")
            for k in sorted(added_keys):
                print(f"        + {k} = {new_cfg[k]}")
        if changed_keys:
            print("-> Changed keys:")
            for k in sorted(changed_keys):
                print(f"        ~ {k}: '{old_cfg[k]}' -> '{new_cfg[k]}'")
        print("-----------------------------------")
    else:
        print("-> No Changes.")

def main():
    check_free_space("/")

    suffix = detect_board_suffix()
    tag, asset_url = fetch_release_asset(suffix)

    tmp_dir = tempfile.mkdtemp(prefix="ota_", dir="/opt")
    boot_dev = root_dev = None

    try:
        tar_path = os.path.join(tmp_dir, "image.tar.gz")
        download(asset_url, tar_path)

        image_path = extract_image(tar_path, tmp_dir)
        os.remove(tar_path)  # free space before mounting

        partitions = read_mbr_partitions(image_path)
        if len(partitions) < 2:
            raise RuntimeError(f"Expected 2 partitions in image, found {len(partitions)}")
        boot_part, root_part = partitions[0], partitions[1]

        os.makedirs(BOOT_MOUNT, exist_ok=True)
        os.makedirs(ROOT_MOUNT, exist_ok=True)

        print("Mounting boot partition...")
        boot_dev = losetup_attach(image_path, boot_part["offset"])
        run(f"mount -t vfat -o ro {boot_dev} {BOOT_MOUNT}")

        print("Mounting root partition...")
        root_dev = losetup_attach(image_path, root_part["offset"])
        run(f"mount -t ext4 -o ro {root_dev} {ROOT_MOUNT}")

        print("Checking for missing files (boot)...")
        copied_boot, overwritten_boot = sync_missing_files(BOOT_MOUNT, "/boot", "boot")
        print("Checking for missing files (root)...")
        copied_root, overwritten_root = sync_missing_files(ROOT_MOUNT, "/", "")
        copied = copied_boot + copied_root
        overwritten = overwritten_boot + overwritten_root
        total = copied + overwritten

        run(f"umount {BOOT_MOUNT}")
        run(f"umount {ROOT_MOUNT}")
        losetup_detach(boot_dev)
        losetup_detach(root_dev)
        boot_dev = root_dev = None

        print(f"Copied {copied} new file(s), overwritten {overwritten} managed file(s).")
        if total > 0:
            print("Running ldconfig...")
            run("ldconfig", check=False)

        update_version_file(tag)

        if total > 0:
            print("Rebooting to apply new files...")
            print("--- DONE ---")
            run("/sbin/reboot", check=False)
        else:
            print("Nothing to apply, no reboot needed.")
            print("--- DONE ---")

    finally:
        if root_dev:
            subprocess.run(f"umount {ROOT_MOUNT}", shell=True, capture_output=True)
            losetup_detach(root_dev)
        if boot_dev:
            subprocess.run(f"umount {BOOT_MOUNT}", shell=True, capture_output=True)
            losetup_detach(boot_dev)
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
