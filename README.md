# Mac Traffic Ledger

**查看每个进程通过代理传了多少数据，以及流量去了哪里。**

面向 macOS + Mihomo / Clash Verge Rev 的本地流量账本。Python 标准库采集器、SQLite 历史数据库和内置网页，无运行时第三方依赖。独立社区项目，与 Clash、Mihomo 或 Clash Verge Rev 无隶属关系。

> 当前为 0.2.0，适合个人使用。按连接采样，不是精确计费器；无法补回安装前的历史。仅统计经过 Mihomo 的连接，不是整机网卡监控。

## 功能

- 按进程名称和可执行文件路径累计上传、下载及总量。
- 点击进程查看域名、IP、代理节点和连接明细。
- 连接详情包括 PID、完整路径、协议、源端口、规则、代理链和观察时间。
- 默认仅显示代理，可切换直连或全部；支持搜索、日期筛选和 CSV 导出。
- 连接明细保留 30 天，每日进程汇总长期保存。
- 登录自动启动；关闭网页不停止记录。
- 显示未知进程流量、采样差额和运行中的采样中断。
- 暖白与陶土色界面，支持系统 / 浅色 / 深色主题；无远程字体或前端依赖。
- 只监听本机地址，不上传数据，不修改代理规则或节点。

## 环境要求

- macOS，Python 3.10 或更新版本。
- 已运行的 Mihomo。默认使用 Clash Verge Rev 的 Unix socket：`/tmp/verge/verge-mihomo.sock`。
- 当前用户能读取该 socket；应用归属使用 macOS `lsof` 和 `libproc`，不需要 root。

## 快速开始

```sh
git clone https://github.com/OHHHHHHei/mac-traffic-ledger.git
cd mac-traffic-ledger
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
mac-traffic-ledger
```

打开 **http://127.0.0.1:8766**。前台运行时用 Ctrl+C 停止。

也可不安装包，直接从源码运行：

```sh
PYTHONPATH=src python3 -m mac_traffic_ledger.ledger
```

不要同时运行前台实例和后台服务，否则会发生端口冲突。

## 登录自动记录

先停止前台实例，然后运行：

```sh
python3 scripts/manage.py install
python3 scripts/manage.py status
```

若通过 pip 安装，也可使用 `mac-traffic-ledger-service install`。

其他命令：

```sh
python3 scripts/manage.py stop       # 停止本次会话；下次登录仍启动
python3 scripts/manage.py start      # 再次启动已安装的服务
python3 scripts/manage.py uninstall  # 停止并取消自动启动，保留数据库
```

服务固定使用执行安装命令时的 Python 解释器和代码位置。移动项目或删除虚拟环境前请先卸载服务；迁移后重新执行 install。

## 使用

1. 选择“今天”“最近 7 天”“本月”或自定义日期。
2. 在进程排行点击某个进程，下方显示它的访问去向和连接。
3. 展开“连接详情”查看 PID、规则、路径和代理链。
4. 切换到“每日账单”查看超过 30 天的历史汇总。
5. 导出当前列表为 CSV。

同一路径的多个 PID 合并展示；不同路径分别记账。连接详情仍保留各自 PID。域名排行最多显示 100 项。连接明细按需加载，每页 50 条，所有匹配连接均可翻页查看；连接 CSV 导出当前页，每日账单 CSV 导出当前筛选结果。汇总卡片包含所有匹配记录。明细筛选精度为分钟；每日账单按整天筛选，搜索只匹配进程和路径。

## 数据存储与配置

默认数据库：`~/Library/Application Support/LocalTrafficLedger/ledger.sqlite3`。

默认服务标识：`local.traffic-ledger`。LaunchAgent 文件位于 `~/Library/LaunchAgents/`，日志位于数据库所在目录。程序源码和历史数据相互独立。

前台运行支持以下环境变量：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `MIHOMO_SOCKET` | `/tmp/verge/verge-mihomo.sock` | 内核 Unix socket |
| `LEDGER_PORT` | `8766` | 本机网页端口 |
| `LEDGER_DATA` | 上述 Application Support 目录 | 数据目录 |

后台服务管理器目前使用默认配置，不会自动继承终端里的上述自定义环境变量。多实例和跨平台服务安装尚未支持。

数据库包含应用路径和访问域名等个人使用记录，请保存在自己的电脑上。程序不记录请求正文、聊天内容或 URL 查询参数。没有云端遥测，也不会公开监听局域网。

## 统计口径与限制

- 首次启动、采集器重启均以活跃连接当前计数作为基线，仅记后续新增字节；停机期间数据不会补算。
- 每秒采样可能漏掉极短连接或连接关闭前的最后一段数据。休眠和离线期间不能记录。
- 运行中恢复采集后，仍存活连接的新增流量会归入恢复时所在分钟，无法还原间隔内的精确发生时间。
- 进程信息优先采用 Mihomo 元数据，否则用完整网络端点匹配系统连接；无法唯一确定的标为“未知进程”。
- 明细使用连接最新识别结果；每日汇总保留入账时的归属，两种视图可能有少量未知进程分配差异，总字节数不变。
- 未归属字节是逐次内核总增量与捕获连接增量的正差估计，含采样边界误差，不是精确漏采率，也不能确定全部属于代理。
- 节点倍率、隧道开销及服务商计费方式未计入；本机统计不等同于套餐账单。
- 连接“最后观察”不是准确断开时间；空闲连接约 15 秒更新一次。采集器离线时活跃状态可能过时。

## 性能设计

正常每秒读取一次内核快照。有新连接或未知连接等待重试时才执行系统连接扫描；归属缓存只保留当前活跃连接。空闲连接每 15 秒刷新。

采集线程复用一个 SQLite 写连接，页面查询使用短生命周期读连接。写缓存目标 2 MiB（不是整个进程内存硬上限），每 10 秒或累计 5000 次数据库行变更提交一次事务；单次大型快照可超过该阈值，下一次循环前立即提交。读查询使用一致性快照，不读取未提交事务。正常退出及离线退避前保存待提交数据，写入异常回滚到上一次已提交的计数基线。

**数据刷新最多延迟约 10 秒；强制终止进程或断电可能丢失尚未提交的最后约 10 秒数据。** 网页自动刷新还有最多 10 秒间隔，看到的数据可能更晚。采集器退出时仍会主动保存。首轮基线行为保持不变。

首页不查询完整连接列表；连接明细按需分页加载，趋势按时段聚合为最多约 121 个点，仍保留分钟级原始统计。首页每 10 秒刷新，明细和每日账单手动刷新，避免阅读中跳动；页面隐藏时停止刷新计时并中止未完成请求。Mihomo 不可用时逐步退避，最多每 30 秒重试。

合成基准（200 条连接、60 次增量采样，不包含 lsof 扫描）：数据库提交从 60 次减至 7 次，采集入库 CPU 时间从约 131ms 减至 95ms，概览响应约 92KB 减至不足 1KB，上下行总数一致。此结果不代表整机 CPU 或耗电同比下降。可用 `PYTHONPATH=src python benchmarks/collector.py` 重现新版基准；附带旧版 ledger.py 路径可进行对比。

开发机短时观测后台主进程约 24 MiB RSS，仅供参考，不包括网页和扫描子进程，不能作为长期内存或耗电保证。

## 项目结构

```text
src/mac_traffic_ledger/
  ledger.py       # 采集、归属、SQLite、HTTP API
  index.html      # 本地统计页面
  style.css       # 主题与响应式布局
  app.js          # 按需查询与页面交互
  manage.py       # macOS 后台服务管理
scripts/manage.py # 源码运行入口
tests/            # 计数、筛选、清理和资源释放测试
```

## 开发与测试

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

GitHub Actions 在 macOS/Linux、Python 3.10/3.12 上运行数据层测试。Linux 测试通过不表示支持 Linux 实时进程采集。请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
