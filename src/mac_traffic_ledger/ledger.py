#!/usr/bin/env python3
"""Local macOS/Mihomo traffic ledger. Python standard library only."""

import collections, csv, ctypes, datetime as dt, http.client, io, json, os, signal, socket, sqlite3, subprocess, tempfile, threading, time, math
from pathlib import Path
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DATA = Path(
    os.environ.get(
        "LEDGER_DATA",
        str(Path.home() / "Library/Application Support/LocalTrafficLedger"),
    )
)
PORT = int(os.environ.get("LEDGER_PORT", "8766"))
SOCK = os.environ.get("MIHOMO_SOCKET")
STOP = threading.Event()
STATUS = {
    "state": "starting",
    "last_success": None,
    "error": None,
    "interval": 1,
    "retention_days": 30,
}
LOCK = threading.RLock()


@contextmanager
def connect():
    c = sqlite3.connect(DATA / "ledger.sqlite3", timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()


def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript("""PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY, started TEXT, first_seen REAL,last_seen REAL, process TEXT,path TEXT,pid INTEGER, attribution TEXT, host TEXT,ip TEXT,source TEXT,sport TEXT,dport TEXT,network TEXT,route TEXT,node TEXT,chain TEXT,rule TEXT, raw_up INTEGER,raw_down INTEGER,active INTEGER);
  CREATE TABLE IF NOT EXISTS samples(bucket INTEGER,id TEXT,up INTEGER,down INTEGER,PRIMARY KEY(bucket,id));
  CREATE INDEX IF NOT EXISTS samples_id ON samples(id);
  CREATE TABLE IF NOT EXISTS daily(day TEXT,process TEXT,path TEXT,route TEXT,up INTEGER,down INTEGER,PRIMARY KEY(day,process,path,route));
  CREATE TABLE IF NOT EXISTS health(bucket INTEGER PRIMARY KEY,core_up INTEGER,core_down INTEGER,seen_up INTEGER,seen_down INTEGER,missed_up INTEGER,missed_down INTEGER,gaps INTEGER);
  CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
  """)
        c.execute("INSERT OR IGNORE INTO meta VALUES('created',?)", (str(time.time()),))
        c.execute("UPDATE connections SET active=0")


def socket_paths():
    if SOCK:
        return [SOCK]
    return list(
        dict.fromkeys(
            [
                f"/var/run/clash-verge-service/users/{os.getuid()}/verge-mihomo.sock",
                "/tmp/verge/verge-mihomo.sock",
                str(Path(tempfile.gettempdir()) / "verge-mihomo.sock"),
            ]
        )
    )


class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        paths = socket_paths()
        for path in paths:
            candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            candidate.settimeout(4)
            try:
                candidate.connect(path)
            except OSError:
                candidate.close()
            else:
                self.sock = candidate
                return
        raise ConnectionError(
            "无法连接 Clash/Mihomo，请确认 Clash 内核正在运行。尝试的通信路径："
            + ", ".join(paths)
        )


def snapshot():
    c = UnixHTTP("localhost", timeout=4)
    try:
        c.request("GET", "/connections")
        r = c.getresponse()
        if r.status != 200:
            raise RuntimeError("Mihomo HTTP " + str(r.status))
        return json.loads(r.read())
    finally:
        c.close()


def endpoints(s):
    a, p = s.rsplit(":", 1)
    return a.strip("[]"), p


def socket_owners():
    r = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-iTCP", "-iUDP", "-FpcPn"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    owners = collections.defaultdict(set)
    pid = 0
    name = ""
    proto = ""
    for l in r.stdout.splitlines():
        if l.startswith("p"):
            pid = int(l[1:])
        elif l.startswith("c"):
            name = l[1:]
        elif l.startswith("P"):
            proto = l[1:].lower()
        elif l.startswith("n") and "->" in l:
            try:
                src, dst = l[1:].split("->")
                sip, sp = endpoints(src)
                dip, dp = endpoints(dst)
                owners[(proto, sip, sp, dip, dp)].add((pid, name))
            except ValueError:
                pass
    return owners


try:
    LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib")
except OSError:
    LIBPROC = None


def pid_path(pid):
    if not LIBPROC:
        return ""
    buf = ctypes.create_string_buffer(4096)
    return (
        buf.value.decode(errors="replace")
        if LIBPROC.proc_pidpath(pid, buf, 4096) > 0
        else ""
    )


def identify(m, owners):
    if m.get("processPath") or m.get("process"):
        return (
            m.get("process") or Path(m["processPath"]).name,
            m.get("processPath", ""),
            0,
            "mihomo",
        )
    ips = {x for x in [m.get("inboundIP"), m.get("destinationIP")] if x}
    found = set()
    for ip in ips:
        found.update(
            owners.get(
                (
                    m.get("network", "").lower(),
                    m.get("sourceIP", ""),
                    str(m.get("sourcePort", "")),
                    ip,
                    str(m.get("destinationPort", "")),
                ),
                set(),
            )
        )
    if len(found) == 1:
        pid, name = next(iter(found))
        return name, pid_path(pid), pid, "socket-exact"
    return "未知进程", "", 0, "unknown"


def delta(current, previous):
    return max(0, current - previous) if current >= previous else max(0, current)


class Collector:
    def __init__(self, flush_interval=0):
        self.flush_interval = flush_interval
        self.db = None
        self.last_commit = 0
        self.committed_changes = 0
        self.checkpoint = None
        self.prev = {}
        self.total = None
        self.last = None
        self.last_cleanup = 0
        self.known = {}
        self.touched = {}
        self.owner_scan = 0

    def flush(self, now=None):
        if self.db is not None:
            self.db.commit()
            self.last_commit = time.time() if now is None else now
            self.committed_changes = self.db.total_changes
            self.checkpoint = (
                self.prev.copy(),
                self.total,
                self.last,
                self.last_cleanup,
                self.known.copy(),
                self.touched.copy(),
            )
            with LOCK:
                STATUS["last_committed"] = self.last_commit

    def close(self):
        if self.db is not None:
            try:
                self.flush()
            finally:
                self.db.close()
                self.db = None

    @contextmanager
    def database(self):
        if self.db is None:
            self.db = sqlite3.connect(DATA / "ledger.sqlite3", timeout=15)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA cache_size=-2048")
        try:
            yield self.db
        except Exception:
            self.db.rollback()
            if self.checkpoint:
                (
                    self.prev,
                    self.total,
                    self.last,
                    self.last_cleanup,
                    self.known,
                    self.touched,
                ) = self.checkpoint
                self.prev = self.prev.copy()
                self.known = self.known.copy()
                self.touched = self.touched.copy()
            else:
                self.prev = {}
                self.total = None
                self.last = None
                self.last_cleanup = 0
                self.known = {}
                self.touched = {}
            raise

    def ingest(self, d, owners, now):
        baseline = self.total is None
        bucket = int(now) // 60 * 60
        day = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        seenup = seendown = 0
        ids = set()
        newprev = {}
        with self.database() as c:
            c.executemany(
                "UPDATE connections SET active=0 WHERE id=?",
                [
                    (i,)
                    for i in self.prev.keys()
                    - {x["id"] for x in d.get("connections", [])}
                ],
            )
            for x in d.get("connections", []):
                ident = x["id"]
                ids.add(ident)
                m = x["metadata"]
                up = x["upload"]
                down = x["download"]
                newprev[ident] = (up, down)
                old = self.prev.get(ident)
                if old is None and not baseline:
                    saved = c.execute(
                        "SELECT raw_up,raw_down FROM connections WHERE id=?", (ident,)
                    ).fetchone()
                    if saved:
                        old = tuple(saved)
                du, dd = (
                    (0, 0)
                    if baseline
                    else (
                        (delta(up, old[0]), delta(down, old[1])) if old else (up, down)
                    )
                )
                seenup += du
                seendown += dd
                existing = self.known.get(ident)
                if existing is None:
                    existing = c.execute(
                        "SELECT process,path,pid,attribution FROM connections WHERE id=?",
                        (ident,),
                    ).fetchone()
                attribution = (
                    identify(m, owners)
                    if not existing or existing[3] == "unknown"
                    else tuple(existing)
                )
                process, path, pid, method = attribution
                self.known[ident] = attribution
                chains = x.get("chains", [])
                route = (
                    "DIRECT"
                    if "DIRECT" in chains
                    else (
                        "REJECT"
                        if any(z.startswith("REJECT") for z in chains)
                        else "PROXY"
                    )
                )
                vals = (
                    ident,
                    x.get("start", ""),
                    now,
                    now,
                    process,
                    path,
                    pid,
                    method,
                    m.get("host") or m.get("sniffHost") or "",
                    m.get("destinationIP") or m.get("remoteDestination") or "",
                    m.get("sourceIP", ""),
                    str(m.get("sourcePort", "")),
                    str(m.get("destinationPort", "")),
                    m.get("network", ""),
                    route,
                    chains[0] if chains else "",
                    json.dumps(chains, ensure_ascii=False),
                    x.get("rule", "") + ": " + x.get("rulePayload", ""),
                    up,
                    down,
                    1,
                )
                if (
                    du
                    or dd
                    or existing is None
                    or tuple(existing) != attribution
                    or now - self.touched.get(ident, 0) >= 15
                ):
                    self.touched[ident] = now
                    c.execute(
                        "INSERT INTO connections VALUES("
                        + ",".join("?" for _ in vals)
                        + ") ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,process=excluded.process,path=excluded.path,pid=excluded.pid,attribution=excluded.attribution,raw_up=excluded.raw_up,raw_down=excluded.raw_down,active=1",
                        vals,
                    )
                if du or dd:
                    c.execute(
                        "INSERT INTO samples VALUES(?,?,?,?) ON CONFLICT(bucket,id) DO UPDATE SET up=up+excluded.up,down=down+excluded.down",
                        (bucket, ident, du, dd),
                    )
                    c.execute(
                        "INSERT INTO daily VALUES(?,?,?,?,?,?) ON CONFLICT(day,process,path,route) DO UPDATE SET up=up+excluded.up,down=down+excluded.down",
                        (day, process, path, route, du, dd),
                    )
            cu = cd = 0
            if not baseline:
                cu = delta(d["uploadTotal"], self.total[0])
                cd = delta(d["downloadTotal"], self.total[1])
            gap = int(self.last is not None and now - self.last > 5)
            c.execute(
                "INSERT INTO health VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(bucket) DO UPDATE SET core_up=core_up+excluded.core_up,core_down=core_down+excluded.core_down,seen_up=seen_up+excluded.seen_up,seen_down=seen_down+excluded.seen_down,missed_up=missed_up+excluded.missed_up,missed_down=missed_down+excluded.missed_down,gaps=gaps+excluded.gaps",
                (
                    bucket,
                    cu,
                    cd,
                    seenup,
                    seendown,
                    max(0, cu - seenup),
                    max(0, cd - seendown),
                    gap,
                ),
            )
            if now - self.last_cleanup > 3600:
                cutoff = int(now - 30 * 86400) // 60 * 60
                c.execute("DELETE FROM samples WHERE bucket<?", (cutoff,))
                c.execute("DELETE FROM health WHERE bucket<?", (cutoff,))
                c.execute(
                    "DELETE FROM connections WHERE last_seen<? AND active=0", (cutoff,)
                )
                self.last_cleanup = now
            self.known = {i: v for i, v in self.known.items() if i in ids}
            self.touched = {i: v for i, v in self.touched.items() if i in ids}
            self.prev = newprev
            self.total = (d["uploadTotal"], d["downloadTotal"])
            self.last = now
            with LOCK:
                STATUS.update(
                    state="recording",
                    last_success=now,
                    error=None,
                    active=len(ids),
                    poll_seconds=1,
                )
            if (
                self.flush_interval == 0
                or now - self.last_commit >= self.flush_interval
                or c.total_changes - self.committed_changes >= 5000
            ):
                self.flush(now)

    def run(self):
        failures = 0
        while not STOP.is_set():
            began = time.monotonic()
            try:
                d = snapshot()
                now = time.time()
                needs_owner = any(
                    not (
                        x["metadata"].get("process") or x["metadata"].get("processPath")
                    )
                    and (
                        x["id"] not in self.known
                        or (
                            self.known[x["id"]][3] == "unknown"
                            and now - self.owner_scan >= 10
                        )
                    )
                    for x in d.get("connections", [])
                )
                owners = socket_owners() if needs_owner else {}
                if needs_owner:
                    self.owner_scan = now
                self.ingest(d, owners, now)
                failures = 0
                with LOCK:
                    STATUS.update(
                        last_cycle_ms=round((time.monotonic() - began) * 1000, 2),
                        owner_scan=needs_owner,
                    )
            except Exception as e:
                failures += 1
                if self.db is not None and self.db.in_transaction:
                    try:
                        self.flush()
                    except sqlite3.Error:
                        pass
                with LOCK:
                    STATUS.update(state="disconnected", error=str(e))
            STOP.wait(
                max(
                    0.05,
                    (min(30, 2 ** min(failures, 5)) if failures else 1)
                    - (time.monotonic() - began),
                )
            )
        self.close()


def query(q):
    now = time.time()
    start = float(q.get("start", [str(now - 86400)])[0])
    end = float(q.get("end", [str(now + 60)])[0])
    route = q.get("route", ["PROXY"])[0]
    search = q.get("search", [""])[0][:200]
    process = q.get("process", [""])[0]
    view = q.get("view", ["overview"])[0]
    page = max(0, int(q.get("page", ["0"])[0]))
    page_size = 50
    if not all(map(math.isfinite, [start, end])) or start > end:
        raise ValueError("Invalid date range")
    start = int(start) // 60 * 60
    end = int(end) // 60 * 60 + 60
    with connect() as c:
        c.execute("BEGIN")  # Consistent read snapshot while the writer commits.
        meta = dict(c.execute("SELECT key,value FROM meta").fetchall())
        if view == "daily":
            wh = ["day>=?", "day<=?"]
            args = [
                dt.datetime.fromtimestamp(start).strftime("%Y-%m-%d"),
                dt.datetime.fromtimestamp(end - 60).strftime("%Y-%m-%d"),
            ]
            if route != "ALL":
                wh.append("route=?")
                args.append(route)
            if search:
                wh.append("(process LIKE ? OR path LIKE ?)")
                args.extend(["%" + search + "%"] * 2)
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM daily WHERE "
                    + " AND ".join(wh)
                    + " ORDER BY day DESC,up+down DESC",
                    args,
                )
            ]
            return {"rows": rows, "status": dict(STATUS), "meta": meta}
        wh = ["s.bucket>=?", "s.bucket<?"]
        args = [start, end]
        if route != "ALL":
            wh.append("c.route=?")
            args.append(route)
        if search:
            wh.append(
                "(c.process LIKE ? OR c.path LIKE ? OR c.host LIKE ? OR c.ip LIKE ?)"
            )
            args.extend(["%" + search + "%"] * 4)
        if process:
            wh.append("c.path=? AND c.process=?")
            p = json.loads(process)
            if (
                not isinstance(p, list)
                or len(p) != 2
                or not all(isinstance(v, str) for v in p)
            ):
                raise ValueError("Invalid process filter")
            args.extend([p[1], p[0]])
        base = " FROM samples s JOIN connections c ON c.id=s.id WHERE " + " AND ".join(
            wh
        )
        if view == "connections":
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT c.*,SUM(s.up) up,SUM(s.down) down"
                    + base
                    + " GROUP BY c.id ORDER BY SUM(s.up+s.down) DESC,c.id LIMIT ? OFFSET ?",
                    args + [page_size, page * page_size],
                )
            ]
            count = c.execute("SELECT COUNT(DISTINCT c.id)" + base, args).fetchone()[0]
            return {
                "connections": rows,
                "count": count,
                "page": page,
                "page_size": page_size,
                "status": dict(STATUS),
            }
        summary = dict(
            c.execute(
                'SELECT COALESCE(SUM(s.up),0) up,COALESCE(SUM(s.down),0) down,COUNT(DISTINCT c.id) connections,COALESCE(SUM(CASE WHEN c.attribution="unknown" THEN s.up+s.down ELSE 0 END),0) unknown'
                + base,
                args,
            ).fetchone()
        )
        processes = [
            dict(r)
            for r in c.execute(
                "SELECT c.process,c.path,SUM(s.up) up,SUM(s.down) down,COUNT(DISTINCT c.id) connections"
                + base
                + " GROUP BY c.process,c.path ORDER BY SUM(s.up+s.down) DESC",
                args,
            )
        ]
        hosts = [
            dict(r)
            for r in c.execute(
                'SELECT COALESCE(NULLIF(c.host,""),c.ip) host,c.route,c.node,SUM(s.up) up,SUM(s.down) down,COUNT(DISTINCT c.id) connections'
                + base
                + " GROUP BY host,c.route,c.node ORDER BY SUM(s.up+s.down) DESC LIMIT 100",
                args,
            )
        ]
        rows = []
        trend_step = max(60, ((end - start + 119) // 120 + 59) // 60 * 60)
        trend = [
            dict(r)
            for r in c.execute(
                "SELECT CAST(s.bucket / ? AS INTEGER)*? bucket,SUM(s.up) up,SUM(s.down) down"
                + base
                + " GROUP BY CAST(s.bucket / ? AS INTEGER) ORDER BY bucket",
                [trend_step, trend_step] + args + [trend_step],
            )
        ]
        health = dict(
            c.execute(
                "SELECT COALESCE(SUM(core_up+core_down),0) core,COALESCE(SUM(missed_up+missed_down),0) missed,COALESCE(SUM(gaps),0) gaps FROM health WHERE bucket>=? AND bucket<?",
                (start, end),
            ).fetchone()
        )
        return {
            "summary": summary,
            "processes": processes,
            "hosts": hosts,
            "connections": rows,
            "trend": trend,
            "health": health,
            "status": dict(STATUS),
            "meta": meta,
            "range": [start, end],
            "page": page,
            "page_size": page_size,
            "trend_step": trend_step,
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        p = urlparse(self.path)
        try:
            if p.path == "/":
                data = (ROOT / "index.html").read_bytes()
                ctype = "text/html; charset=utf-8"
            elif p.path in ("/style.css", "/app.js"):
                data = (ROOT / p.path[1:]).read_bytes()
                ctype = (
                    "text/css; charset=utf-8"
                    if p.path.endswith(".css")
                    else "text/javascript; charset=utf-8"
                )
            elif p.path == "/api/data":
                data = json.dumps(query(parse_qs(p.query)), ensure_ascii=False).encode()
                ctype = "application/json; charset=utf-8"
            elif p.path == "/api/export":
                q = parse_qs(p.query)
                if q.get("view", [""])[0] != "daily":
                    q["view"] = ["connections"]
                result = query(q)
                rows = result.get("rows", result.get("connections", []))
                out = io.StringIO()
                w = csv.DictWriter(out, fieldnames=list(rows[0]) if rows else ["id"])
                w.writeheader()
                for row in rows:
                    w.writerow(
                        {
                            k: (
                                "'" + v
                                if isinstance(v, str)
                                and v.startswith(("=", "+", "-", "@"))
                                else v
                            )
                            for k, v in row.items()
                        }
                    )
                data = ("\ufeff" + out.getvalue()).encode()
                ctype = "text/csv; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if p.path == "/api/export":
                self.send_header(
                    "Content-Disposition", 'attachment; filename="traffic-ledger.csv"'
                )
            self.end_headers()
            self.wfile.write(data)
        except (ValueError, TypeError, OverflowError, json.JSONDecodeError):
            self.send_error(400)
        except BrokenPipeError:
            pass


def main():
    init()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)

    def shutdown(*_):
        STOP.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    collector = Collector(flush_interval=10)
    t = threading.Thread(target=collector.run, daemon=True)
    t.start()
    print("Traffic Ledger http://127.0.0.1:" + str(PORT), flush=True)
    server.serve_forever()
    STOP.set()
    t.join(20)
    server.server_close()


if __name__ == "__main__":
    main()
