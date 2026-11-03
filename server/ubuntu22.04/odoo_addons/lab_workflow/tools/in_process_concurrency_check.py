#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程内并发验收的**独立进程适配器**（复用原用例类与原断言，不走测试框架）。

为什么需要它
============

``tests/test_workflow_concurrency.py`` 的 6 个场景要求「两个事务真实相交 +
各自真实提交」。但在 ``odoo-bin --test-enable`` 进程里，``api.Environment(cr, …)``
会执行 ``Transaction(Registry(cr.dbname))``，而 ``Registry.__new__`` 要拿
``Registry._lock``；实测该锁在测试进程里被长期持有，工作线程拿到连接后就卡在
``Environment`` 上（``pg_stat_activity`` 没有未授予锁，不是数据库行锁），
每个用例恰好卡满 ``join`` 超时。

本适配器把**同一个用例类、同一套断言**放到**没有 --test-enable 的独立进程**里跑：

* 不存在 registry 测试模式（``registry.cursor`` 未 patch、没有 ``TestCursor``）；
* 没有 ``--test-enable`` 的加载/测试线程持有 ``Registry._lock``；
* 每个线程仍是**真实独立连接 + 真实 commit**（``_real_cursor``）。

它**不新增/不削弱任何断言**：直接 import ``LabWorkflowConcurrencyTest``，逐个调用
它的 ``test_0x_*`` 方法（每个场景独立 ``setUp()/tearDown()``，夹具逐用例隔离，
因此前一场的袋不会污染后一场的计数），异常（AssertionError / 业务异常）一律计 FAIL，
并把用例写入的 ``case.evidence``（如 06 的失败分类、残留计数）带进 JSON。

退出码
======

* ``0`` 全部场景通过，且负向自检（故意失败的断言必须被记为 FAIL）也通过；
* ``1`` 有场景失败（含断言失败）——**非零退出，失败数如实汇报**；
* ``2`` BLOCKED：无法引导 Odoo / 环境仍是测试模式 / 场景没收集全 / 负向自检失灵。

用法（由 Lead 在隔离运行时里执行，命令本身不写入仓库）
=====================================================

::

    LAB_WORKFLOW_CONCURRENCY=1 \\
    $R/opt/odoo-venv/bin/python tools/in_process_concurrency_check.py \\
        --conf /tmp/labwf/odoo.conf --db labwf_test \\
        --addons-path /tmp/labwf/addons/custom,/opt/odoo/addons,/opt/odoo/odoo/addons

    可选：--json-out <path> 写机器可读结果；--timeout 20 覆盖单场景 barrier 秒数。

注意：必须在**安装完成后**、含真实三模块的库上运行（脚本只读加载 registry，
不执行 -i/-u，不写业务数据，除用例自己创建的夹具外不改库）。
"""

from __future__ import print_function

import argparse
import json
import logging
import os
import sys
import time
import traceback
import unittest

_logger = logging.getLogger('lab_concurrency_adapter')

EXPECTED_SCENARIOS = (
    'test_01_two_threads_issue_70_of_100',
    'test_02_two_threads_return_15_of_20',
    'test_03_same_request_key_two_threads_receipt',
    'test_04_same_key_different_payload_concurrent',
    'test_05_two_keys_confirm_one_prepared_bag',
    'test_06_two_managers_concurrent_revoke_keeps_one',
)


# ---------------------------------------------------------------------------
# Odoo 引导（不启动 HTTP / 服务器；只加载 registry）
# ---------------------------------------------------------------------------
def bootstrap_odoo(conf, db, addons_path=None):
    """解析配置并返回 (registry, 环境事实 dict)。失败直接抛异常。"""
    import odoo  # noqa: F401  - 必须先 import 才会建立 tools.config
    from odoo.tools import config

    argv = ['-c', conf, '-d', db, '--no-http']
    if addons_path:
        argv += ['--addons-path', addons_path]
    config.parse_config(argv, setup_logging=True)

    if config['test_enable']:
        raise RuntimeError(
            '进程仍处于测试模式（test_enable=True）；本适配器必须在不带 '
            '--test-enable 的进程里运行，否则会重新撞上框架锁。')
    # get_db_name() 需要单库
    if not config['db_name']:
        config['db_name'] = [db]
    elif config['db_name'] != [db] and list(config['db_name']) != [db]:
        config['db_name'] = [db]

    try:
        from odoo.orm.registry import Registry
    except ImportError:  # 兼容 19.0 早期布局
        from odoo.modules.registry import Registry

    started = time.time()
    registry = Registry(db)
    facts = {
        'odoo_version': getattr(odoo.release, 'version', None),
        'python': sys.version.split()[0],
        'db': db,
        'conf': conf,
        'addons_path': list(config['addons_path']),
        'registry_load_seconds': round(time.time() - started, 3),
        'test_enable': bool(config['test_enable']),
        'registry_cursor_patched': 'cursor' in vars(registry),
    }
    if facts['registry_cursor_patched']:
        raise RuntimeError(
            'registry.cursor 仍被测试框架 patch（TestCursor）；'
            '这不是独立进程环境，拒绝把结果当并发证据。')
    return registry, facts


# ---------------------------------------------------------------------------
# 结果收集
# ---------------------------------------------------------------------------
def exercise(name, fn):
    """执行一个场景，返回结构化结果（异常一律 FAIL，不把异常算成功）。"""
    started = time.time()
    record = {'name': name, 'result': 'fail', 'seconds': 0.0,
              'error_type': '', 'detail': ''}
    try:
        fn()
        record['result'] = 'pass'
    except unittest.SkipTest as exc:
        record['result'] = 'blocked'
        record['error_type'] = 'SkipTest'
        record['detail'] = str(exc)
    except AssertionError as exc:
        record['error_type'] = 'AssertionError'
        record['detail'] = str(exc)
        record['traceback'] = traceback.format_exc()
    except Exception as exc:  # noqa: BLE001 - 业务/DB 异常都算失败
        record['error_type'] = type(exc).__name__
        record['detail'] = '%s: %s' % (type(exc).__name__, exc)
        record['traceback'] = traceback.format_exc()
    finally:
        record['seconds'] = round(time.time() - started, 3)
    return record


def scenario_callable(test_cls, method_name, sink):
    """把用例方法包装成普通 callable（setUp/tearDown 与 unittest 一致）。

    ``sink`` 用于带出用例自己记录的 ``case.evidence``（例如 test_06 的
    “失败类型=last_manager / concurrency_abort”），让 JSON 里有可核对的证据，
    而不是只有 pass/fail。
    """
    def run():
        case = test_cls(method_name)
        try:
            case.setUp()
            getattr(case, method_name)()
        finally:
            try:
                case.tearDown()
            except Exception:  # noqa: BLE001 - tearDown 异常不应掩盖断言结论
                _logger.warning('%s tearDown 异常（不影响断言结论）', method_name,
                                exc_info=True)
            sink['evidence'] = getattr(case, 'evidence', None)
    return run


def negative_control():
    """负向自检：故意失败的断言**必须**被记为 FAIL。

    这是“非零验证”的一部分：证明适配器不会把失败吞成成功。
    """
    def boom():
        raise AssertionError('负向自检：这条断言必须失败（预期被记录为 FAIL）')

    record = exercise('negative-control', boom)
    detected = (record['result'] == 'fail'
                and record.get('error_type') == 'AssertionError')
    record['detected'] = detected
    return record


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description='lab_workflow 进程内并发验收（独立进程适配器，复用原用例与断言）')
    parser.add_argument('--conf', required=True, help='odoo.conf 路径（隔离运行时的）')
    parser.add_argument('--db', required=True, help='隔离测试库名')
    parser.add_argument('--addons-path', default=None,
                        help='覆盖 addons_path（逗号分隔，含真实三模块目录）')
    parser.add_argument('--timeout', type=int, default=None,
                        help='barrier 超时秒数，写入 LAB_WORKFLOW_CONCURRENCY_TIMEOUT')
    parser.add_argument('--json-out', default=None, help='把结果写成 JSON 文件')
    args = parser.parse_args(argv)

    os.environ['LAB_WORKFLOW_CONCURRENCY'] = '1'
    if args.timeout:
        os.environ['LAB_WORKFLOW_CONCURRENCY_TIMEOUT'] = str(args.timeout)

    summary = {'kind': 'lab-concurrency-in-process-adapter', 'results': [],
               'negative_control': None, 'facts': {}, 'blocked_reason': None,
               'counts': {'total': 0, 'pass': 0, 'fail': 0, 'blocked': 0}}
    exit_code = 2

    try:
        registry, facts = bootstrap_odoo(args.conf, args.db, args.addons_path)
        summary['facts'] = facts
    except Exception as exc:  # noqa: BLE001 - 引导失败=BLOCKED，不是通过
        summary['blocked_reason'] = 'bootstrap: %s: %s' % (
            type(exc).__name__, exc)
        _logger.error('BLOCKED：%s', summary['blocked_reason'])
        summary['blocked_traceback'] = traceback.format_exc()
        _write_json(args.json_out, summary)
        return 2

    try:
        # 必须在导入测试模块前设置开关：模块级 CONCURRENCY_ENABLED 在 import 时求值
        import importlib
        test_module = importlib.import_module(
            'odoo.addons.lab_workflow.tests.test_workflow_concurrency')
    except Exception as exc:  # noqa: BLE001
        summary['blocked_reason'] = 'import: %s: %s' % (type(exc).__name__, exc)
        _logger.error('BLOCKED：%s', summary['blocked_reason'])
        summary['blocked_traceback'] = traceback.format_exc()
        _write_json(args.json_out, summary)
        return 2

    test_cls = getattr(test_module, 'LabWorkflowConcurrencyTest', None)
    if test_cls is None:
        summary['blocked_reason'] = '找不到 LabWorkflowConcurrencyTest'
        _write_json(args.json_out, summary)
        return 2

    setup_error = None
    try:
        test_cls.setUpClass()
    except unittest.SkipTest as exc:
        setup_error = 'SkipTest: %s' % exc
    except Exception:  # noqa: BLE001
        setup_error = 'setUpClass: %s' % traceback.format_exc()

    if setup_error:
        summary['blocked_reason'] = setup_error
        _logger.error('BLOCKED：%s', setup_error)
        try:
            test_cls.doClassCleanups()
        except Exception:  # noqa: BLE001
            pass
        _write_json(args.json_out, summary)
        return 2

    try:
        collected = [name for name in dir(test_cls)
                     if name.startswith('test_') and callable(getattr(test_cls, name))]
        collected.sort()
        missing = [name for name in EXPECTED_SCENARIOS if name not in collected]
        if missing:
            summary['blocked_reason'] = '场景未收集全，缺：%s' % ', '.join(missing)
            _logger.error('BLOCKED：%s', summary['blocked_reason'])
            _write_json(args.json_out, summary)
            return 2

        for name in EXPECTED_SCENARIOS:
            _logger.info('=== 场景 %s ===', name)
            sink = {}
            record = exercise(name, scenario_callable(test_cls, name, sink))
            if sink.get('evidence'):
                record['evidence'] = sink['evidence']
            summary['results'].append(record)
            counts = summary['counts']
            counts['total'] += 1
            counts[record['result']] += 1
            _logger.info('场景 %s：%s（%.2fs）%s', name, record['result'],
                         record['seconds'],
                         ('— ' + record['detail']) if record['detail'] else '')
    finally:
        try:
            test_cls.tearDownClass()
        except Exception:  # noqa: BLE001 - 清理失败不改变断言结论
            _logger.warning('tearDownClass 清理异常（不影响结论）', exc_info=True)
        try:
            test_cls.doClassCleanups()
        except Exception:  # noqa: BLE001
            pass

    control = negative_control()
    summary['negative_control'] = control
    _logger.info('负向自检：%s（%s）', control['detected'], control['detail'])

    counts = summary['counts']
    print('\n===== 进程内并发结果（独立进程，非 --test-enable）=====')
    for record in summary['results']:
        print('%-58s %-8s %6.2fs %s' % (
            record['name'], record['result'].upper(), record['seconds'],
            record['detail'][:160]))
    print('统计：total=%d pass=%d fail=%d blocked=%d；负向自检=%s'
          % (counts['total'], counts['pass'], counts['fail'], counts['blocked'],
             'detected' if control['detected'] else 'BROKEN'))

    if not control['detected']:
        summary['blocked_reason'] = '负向自检失灵：故意失败的断言没有被记为 FAIL'
        exit_code = 2
    elif counts['blocked']:
        summary['blocked_reason'] = '有场景 BLOCKED'
        exit_code = 2
    elif counts['fail']:
        exit_code = 1
    elif counts['pass'] == len(EXPECTED_SCENARIOS):
        exit_code = 0
    else:
        summary['blocked_reason'] = '场景数不符：pass=%d，期望 %d' % (
            counts['pass'], len(EXPECTED_SCENARIOS))
        exit_code = 2

    summary['exit_code'] = exit_code
    _write_json(args.json_out, summary)
    print('退出码：%d（0=通过 / 1=有失败 / 2=BLOCKED）' % exit_code)
    return exit_code


def _write_json(path, summary):
    if not path:
        return
    try:
        with open(path, 'w') as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:  # noqa: BLE001 - 写不出结果不应改变退出码语义
        _logger.warning('写结果 JSON 失败：%s', path, exc_info=True)


if __name__ == '__main__':
    sys.exit(main())
