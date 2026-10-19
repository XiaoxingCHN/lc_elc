# Ubuntu/Odoo依赖准备器

当前入口是[依赖获取说明](../README.md)和根docs/operations/SERVER.md。本目录脚本/lib与server/ubuntu22.04内部相对布局保持兼容；指定新的WORK_DIR/OUT_DIR运行，不覆盖已核验out。原README包含早期未验收状态，已保存local/archive/docs-original/server-dependencies-original.md。

现有out为cp310准备闭包；实际生产cp312的公开包版本锁另在maintenance/registry，完整cp312 wheelhouse尚未生成验收。
