#!/bin/bash
# lab_theme 部署脚本（已按实际环境校正）
# 用法: bash deploy-theme.sh [数据库名]
set -euo pipefail

DB="${1:-LcHardwareHouse}"
ODOO_BIN=/opt/odoo/odoo-19/odoo-bin
ODOO_PY=/opt/odoo/venv/bin/python3
ODOO_CONF=/etc/odoo.conf
MODULE=lab_theme

echo "=== 部署 $MODULE 到 $DB ==="
systemctl is-active odoo || true

echo "--- 停止 Odoo ---"
sudo systemctl stop odoo

echo "--- 安装/升级模块 ---"
sudo -u odoo "$ODOO_PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$DB" -u "$MODULE" --stop-after-init

echo "--- 启动 Odoo ---"
sudo systemctl start odoo
sleep 6
systemctl is-active odoo

echo "=== 完成，浏览器请 Ctrl+Shift+R 强制刷新 ==="
