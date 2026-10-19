#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo '请用 sudo bash install_crawler.sh /数据解压目录' >&2; exit 1; fi
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 22.04 ]] || { echo '此脚本仅面向Ubuntu22.04'; exit 1; }
base=$(cd -- "$(dirname -- "$0")" && pwd)
data=$(realpath -- "${1:?请传入包含components.sqlite3和manifest的目录}")
[[ -f "$data/components.sqlite3" && -f "$data/components.manifest.json" && -f "$data/categories_cn.json" ]] || { echo '数据文件不完整'; exit 1; }
if systemctl is-active --quiet lcsc-crawler; then echo '采集服务仍运行，请先安全停止'; exit 1; fi
[[ ! -e /var/lib/lcsc-crawler/components.sqlite3 ]] || { echo '目标数据库已经存在，拒绝覆盖；请按更新文档处理'; exit 1; }
python3 "$base/verify_checkpoint.py" "$data"
apt-get update
apt-get install -y python3 python3-venv python3-pip
if ! getent passwd lcsc >/dev/null; then
  useradd --system --home-dir /var/lib/lcsc-crawler --shell /usr/sbin/nologin lcsc
fi
install -d -m 0755 /opt/lcsc-crawler/app
install -d -o lcsc -g lcsc -m 0750 /var/lib/lcsc-crawler
for file in lcsc_catalog_archive.py lcsc_electronics_filter.json requirements.txt snapshot_catalog.py; do
  install -m 0644 "$base/crawler/$file" /opt/lcsc-crawler/app/
done
python3 -m venv /opt/lcsc-crawler/.venv
/opt/lcsc-crawler/.venv/bin/python -m pip install -r /opt/lcsc-crawler/app/requirements.txt
python3 - /var/lib/lcsc-crawler "$data/components.sqlite3" <<'PY'
import shutil,sys,pathlib
assert shutil.disk_usage(sys.argv[1]).free > pathlib.Path(sys.argv[2]).stat().st_size + 2*1024**3, '目标磁盘空间不足'
PY
install -o lcsc -g lcsc -m 0600 "$data/components.sqlite3" /var/lib/lcsc-crawler/components.sqlite3
install -o lcsc -g lcsc -m 0640 "$data/categories_cn.json" /var/lib/lcsc-crawler/categories_cn.json
install -m 0644 "$base/systemd/lcsc-crawler.service" /etc/systemd/system/lcsc-crawler.service
systemd-analyze verify /etc/systemd/system/lcsc-crawler.service
systemctl daemon-reload
echo '安装完成，服务尚未启动且未启用自启。请按安装手册先小批验证。'
