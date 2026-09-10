#!/usr/bin/env python3
"""Switch zhushou.lingheltd.top /api proxy between V1(:8000) and V2(:18001).

Usage:
  nginx_cutover.py --switch        # point /api to V2(18001), backup current config
  nginx_cutover.py --rollback      # restore latest backup (/api to V1:8000)
  nginx_cutover.py --status        # show current target and backups
"""
import sys, os, glob, shutil, subprocess, time

SITE = "/etc/nginx/sites-enabled/pdd-kpi"
BACKUP_DIR = "/etc/nginx/backups"
V1 = "http://127.0.0.1:8000"
V2 = "http://127.0.0.1:18001"

def run(cmd, check=True):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.stderr.write("CMD FAILED: %s\n%s%s" % (cmd, r.stdout, r.stderr))
        sys.exit(r.returncode)
    return r

def current_target():
    if not os.path.exists(SITE):
        return None
    with open(SITE) as f:
        text = f.read()
    if "127.0.0.1:18001" in text:
        return "v2"
    if "127.0.0.1:8000" in text:
        return "v1"
    return "unknown"

def apply(text):
    tmp = SITE + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    shutil.move(tmp, SITE)
    run("nginx -t")
    run("systemctl reload nginx")
    # smoke test: V2 must be up after switch
    time.sleep(2)
    r = run("curl -fsS http://127.0.0.1:18001/health || true", check=False)
    if "ok" not in r.stdout:
        sys.stderr.write("WARNING: V2 health check did not return ok after switch\n")
        return 2
    return 0

def do_switch():
    if not os.path.exists(SITE):
        sys.exit("site config not found: %s" % SITE)
    with open(SITE) as f:
        orig = f.read()
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d%H%M%S")
    backup = os.path.join(BACKUP_DIR, "pdd-kpi.v1-%s.bak" % ts)
    with open(backup, "w") as f:
        f.write(orig)
    new = orig.replace("proxy_pass http://127.0.0.1:8000;", "proxy_pass http://127.0.0.1:18001;")
    if new == orig:
        sys.exit("already switched to V2 (no 127.0.0.1:8000 proxy_pass found)")
    run("cp %s %s" % (SITE, backup + ".2"))
    rc = apply(new)
    print("SWITCHED /api -> V2(18001); backup=%s" % backup)
    print("validate via https://zhushou.lingheltd.top/api/health")
    return rc

def do_rollback():
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "pdd-kpi*.bak")))
    if not backups:
        sys.exit("no backups found")
    latest = backups[-1]
    with open(latest) as f:
        text = f.read()
    rc = apply(text)
    print("ROLLED BACK /api -> V1(8000) using %s" % latest)
    return rc

def do_status():
    print("target: %s" % current_target())
    for b in sorted(glob.glob(os.path.join(BACKUP_DIR, "pdd-kpi*.bak"))):
        print("backup: %s" % b)

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--switch" in args:
        sys.exit(do_switch())
    elif "--rollback" in args:
        sys.exit(do_rollback())
    elif "--status" in args or not args:
        do_status()
    else:
        sys.exit("usage: --switch | --rollback | --status")