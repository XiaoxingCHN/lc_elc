#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo '请用sudo运行'; exit 1; }
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 && $(dpkg --print-architecture) == amd64 ]] || { echo '仅支持Ubuntu22.04 amd64'; exit 1; }
base=$(cd -- "$(dirname -- "$0")" && pwd)
mode=${1:-}; deps=$(realpath -- "${2:?需要服务器依赖out目录}")
[[ $mode == --crawler || $mode == --fresh-odoo ]] || { echo '用法: sudo bash install_offline.sh --crawler 依赖out目录 数据目录'; echo '或: sudo bash install_offline.sh --fresh-odoo 依赖out目录'; exit 1; }
[[ -f "$deps/SHA256SUMS" && -f "$deps/debs/Packages" ]] || { echo '缺少完整依赖包'; exit 1; }
(cd "$deps" && sha256sum -c SHA256SUMS --quiet)
if [[ $mode == --crawler ]]; then
  data=$(realpath -- "${3:?需要数据库快照目录}")
  [[ ! -e /var/lib/lcsc-crawler/components.sqlite3 ]] || { echo '目标库已存在，拒绝覆盖'; exit 1; }
  python3 "$base/verify_checkpoint.py" "$data"
else
  python3 - "$base/odoo_addons" <<'PY'
import ast,pathlib,sys
root=pathlib.Path(sys.argv[1])
for name in ('lab_inventory','lab_catalog','lab_workflow'):
    addon=root/name
    manifest=ast.literal_eval((addon/'__manifest__.py').read_text(encoding='utf-8-sig'))
    for file in manifest.get('data',[]):
        assert (addon/file).is_file(), f'业务包不完整: {name}/{file}'
print('业务模块文件预检通过')
PY
  [[ ! -e /etc/odoo.conf && ! -e /opt/odoo/odoo-19 ]] || { echo '检测到已有Odoo配置/源码，拒绝全新安装；采集器请用--crawler'; exit 1; }
  read -r -s -p '设置Odoo管理员登录密码（至少12字符）: ' LC_ELC_BOOTSTRAP_ADMIN_PASSWORD; echo
  [[ ${#LC_ELC_BOOTSTRAP_ADMIN_PASSWORD} -ge 12 ]] || { echo '密码不足12字符，安装未开始'; exit 1; }
  export LC_ELC_BOOTSTRAP_ADMIN_PASSWORD
fi
# 固定本地仓库，避免_apt无法读取管理员家目录。
repo=/opt/lc-elc-dependencies/debs
install -d -m 0755 "$repo"
cp -a "$deps/debs/." "$repo/"
find "$repo" -type f -exec chmod 0644 {} +
list=/etc/apt/sources.list.d/lc-elc-offline.list
printf 'deb [trusted=yes] file:%s ./\n' "$repo" > "$list"
aptargs=(-o "Dir::Etc::sourcelist=$list" -o 'Dir::Etc::sourceparts=-' -o APT::Get::List-Cleanup=0)
apt-get "${aptargs[@]}" update
export DEBIAN_FRONTEND=noninteractive
if [[ $mode == --crawler ]]; then
  apt-get "${aptargs[@]}" install -y --no-install-recommends python3 python3-venv python3-pip
  if ! getent passwd lcsc >/dev/null; then useradd --system --home-dir /var/lib/lcsc-crawler --shell /usr/sbin/nologin lcsc; fi
  install -d -m 0755 /opt/lcsc-crawler/app
  install -d -o lcsc -g lcsc -m 0750 /var/lib/lcsc-crawler
  for file in lcsc_catalog_archive.py lcsc_electronics_filter.json requirements.txt snapshot_catalog.py; do
    install -m 0644 "$base/crawler/$file" /opt/lcsc-crawler/app/
  done
  python3 -m venv /opt/lcsc-crawler/.venv
  /opt/lcsc-crawler/.venv/bin/pip install --no-index --no-build-isolation --find-links "$deps/wheelhouse-crawler" -r "$deps/crawler-requirements.txt"
  /opt/lcsc-crawler/.venv/bin/pip check
  python3 - "$data/components.sqlite3" <<'PY'
import pathlib,shutil,sys
assert shutil.disk_usage('/var/lib/lcsc-crawler').free>pathlib.Path(sys.argv[1]).stat().st_size+2*1024**3, '磁盘不足'
PY
  install -o lcsc -g lcsc -m 0600 "$data/components.sqlite3" /var/lib/lcsc-crawler/components.sqlite3
  install -o lcsc -g lcsc -m 0640 "$data/categories_cn.json" /var/lib/lcsc-crawler/categories_cn.json
  install -m 0644 "$base/systemd/lcsc-crawler.service" /etc/systemd/system/lcsc-crawler.service
  systemd-analyze verify /etc/systemd/system/lcsc-crawler.service
  systemctl daemon-reload
  echo '采集器离线安装完成，尚未启动。请先小批验证，再systemctl start lcsc-crawler。'
  exit 0
fi
# 全新Odoo安装；不覆盖已有数据库。
apt-get "${aptargs[@]}" install -y --no-install-recommends \
  python3 python3-venv python3-pip postgresql-14 python3-gevent python3-greenlet \
  python3-lxml python3-psycopg2 python3-ldap python3-pil python3-psutil
systemctl start postgresql
for attempt in {1..30}; do
  if runuser -u postgres -- pg_isready -q; then break; fi
  sleep 1
done
runuser -u postgres -- pg_isready -q || { echo 'PostgreSQL未在30秒内就绪，安装停止'; exit 1; }
exists=$(runuser -u postgres -- psql -Atqc "SELECT 1 FROM pg_database WHERE datname='LcHardwareHouse'")
[[ -z $exists ]] || { echo 'LcHardwareHouse已经存在，拒绝继续新建'; exit 1; }
if ! getent passwd odoo >/dev/null; then useradd --system --home-dir /opt/odoo --shell /usr/sbin/nologin odoo; fi
runuser -u odoo -- python3 -c 'import os; assert len(os.environ.get("LC_ELC_BOOTSTRAP_ADMIN_PASSWORD", "")) >= 12, "管理员密码环境未传递，安装停止"'
if [[ -z $(runuser -u postgres -- psql -Atqc "SELECT 1 FROM pg_roles WHERE rolname='odoo'") ]]; then
  runuser -u postgres -- createuser --createdb --no-createrole --no-superuser odoo
fi
install -d -o odoo -g odoo /opt/odoo/odoo-19 /opt/odoo/custom-addons /var/lib/odoo /var/log/odoo
archive=$(find "$deps/odoo" -maxdepth 1 -name 'odoo-*.tar.gz' -print -quit)
[[ -n $archive ]] || { echo '缺少Odoo源码'; exit 1; }
tar -xzf "$archive" --strip-components=1 -C /opt/odoo/odoo-19
for addon in lab_inventory lab_catalog lab_workflow; do
  [[ -f "$base/odoo_addons/$addon/__manifest__.py" ]] || { echo "缺少业务模块: $addon"; exit 1; }
  cp -a "$base/odoo_addons/$addon" /opt/odoo/custom-addons/
done
chown -R odoo:odoo /opt/odoo/odoo-19 /opt/odoo/custom-addons
install -d -m 0755 /opt/lc-elc-tools
install -o root -g odoo -m 0750 "$base/import_catalog_config.py" /opt/lc-elc-tools/import_catalog_config.py
python3 -m venv --system-site-packages /opt/odoo/venv
/opt/odoo/venv/bin/pip install --no-index --no-build-isolation --find-links "$deps/wheelhouse-odoo" -r "$deps/odoo/odoo-requirements.txt"
/opt/odoo/venv/bin/pip check
/opt/odoo/venv/bin/python "$base/tools/check_barcode_rendering.py"
/opt/odoo/venv/bin/python -c 'import gevent,ldap,psycopg2,lxml;print("Odoo native dependencies import OK")'
python3 - "$base/odoo.conf.example" <<'PY'
import pathlib,secrets,sys
s=pathlib.Path(sys.argv[1]).read_text().replace('REPLACE_WITH_RANDOM_MASTER_PASSWORD',secrets.token_urlsafe(36)).replace('http_interface = 0.0.0.0','http_interface = 127.0.0.1')
pathlib.Path('/etc/odoo.conf').write_text(s)
PY
chown root:odoo /etc/odoo.conf; chmod 0640 /etc/odoo.conf
runuser -u postgres -- createdb --owner=odoo LcHardwareHouse
runuser -u odoo -- /opt/odoo/venv/bin/python /opt/odoo/odoo-19/odoo-bin -c /etc/odoo.conf -d LcHardwareHouse -i base,lab_inventory,lab_catalog,lab_workflow --stop-after-init --no-http
runuser -u odoo -- /opt/odoo/venv/bin/python /opt/odoo/odoo-19/odoo-bin shell -c /etc/odoo.conf -d LcHardwareHouse --no-http <<'PY'
import os
env.ref('base.user_admin').write({'password': os.environ['LC_ELC_BOOTSTRAP_ADMIN_PASSWORD']})
env.cr.commit()
PY
unset LC_ELC_BOOTSTRAP_ADMIN_PASSWORD
install -m 0644 "$base/systemd/odoo.service.example" /etc/systemd/system/odoo.service
systemd-analyze verify /etc/systemd/system/odoo.service
systemctl daemon-reload
echo 'Odoo离线安装完成，管理员密码已设置。仅监听127.0.0.1，尚未启动。'
echo '先systemctl start odoo，通过SSH转发测试；内网开放或HTTPS按安装手册配置。'
