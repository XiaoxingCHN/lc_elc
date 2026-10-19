# EDA3.0.3维护

## 源与运行时

src/main是EDA入口，src/iframe是业务面板，scripts/build.mjs负责构建eext/bundle，bridge/server.mjs是零npm第三方运行依赖的本机桥接。桥接不是Python/PyInstaller。

Windows runtime为bridge/runtime/node.exe v24.19.0（92825416字节），匹配NODE-LICENSE.txt。hash `3602f2bb1a10f2cbab4c36886218a33c1ab3db87290e73b033c46c77147d0237`。从已核对当前bundle提取bridge/runtime即可恢复同字节；_reference的24.13.0不是当前版本。Linux启动脚本需Linux Node≥20.5，Windows exe不能用于Linux。

构建依赖package-lock.json锁定esbuild0.25.10、jszip3.10.1及完整registry URL/integrity。当前node_modules已本地保留但Git排除；联网机器从本目录运行 `npm ci --cache ../../dependencies/npm-cache --no-audit --no-fund` 可获取。离线恢复必须先有完整npm缓存，不能把‘有node_modules’写成‘npm ci --offline通过’。本次新缓存准备遇到网络超时，CURRENT_STATE会保留实际结果。

## 测试与构建

```sh
npm ci --cache ../../dependencies/npm-cache --no-audit --no-fund
npm test
npm run test:package
npm run verify
```

build会清空本组件build/dist，属于生成物；当前release在独立releases目录，不能覆盖。构建前冻结source manifest，修改package.json与extension.json版本要一致。

既有日志105单测/13包测试通过；本次归档会从新路径重新执行可执行检查，具体本轮结果另记录。实际EDA宿主导入交互不因Node单测通过就算实机重测。

## 成品与权限边界

当前eext SHA `69665cbf3fac0732db7f6b01188014ac773dbc3d43e12062e8ffd039016998ef`，完整bundle SHA `5b48babfe8cb365c30588f79bb6e1c549769899ee95d75dabde4a6328cbf784b`。

桥接仅监听127.0.0.1，启动生成配对码，服务器会话保留桥接内部，不把cookie交给EDA；密码不落盘。写库存前需要确认和服务端权限，不用插件UI隐藏替代后端鉴权。默认IP/DB仅为旧环境定位，迁服务器需同时维护bridge配置和集成验收。
