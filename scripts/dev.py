import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def listening(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    os.chdir(ROOT)
    os.environ["PYTHONUTF8"] = "1"
    if not (ROOT / ".env").is_file():
        raise RuntimeError("缺少 .env，请先按 README 配置")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("请先运行 npm --prefix frontend run build")
    subprocess.run(["docker", "compose", "up", "-d", "--wait", "--wait-timeout", "180"], check=True)
    processes = []
    handles = []
    logs = ROOT / "data/runtime-logs"
    logs.mkdir(parents=True, exist_ok=True)
    services = [
        ("logistics", 8111, ["-m", "mcp_servers.logistics_server"]),
        ("aftersales", 8112, ["-m", "mcp_servers.aftersales_server"]),
        ("api", 8010, ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"]),
    ]
    try:
        for name, port, arguments in services:
            if listening(port):
                if name == "api":
                    import json
                    with urlopen("http://127.0.0.1:8010/health", timeout=3) as response:
                        if json.load(response).get("service") != "eshop-assistant":
                            raise RuntimeError("8010 被其他服务占用")
                print(f"{name}: 端口 {port} 已有服务，保留现有进程", flush=True)
                continue
            output = (logs / f"{name}.out.log").open("a", encoding="utf-8")
            error = (logs / f"{name}.err.log").open("a", encoding="utf-8")
            handles.extend([output, error])
            process = subprocess.Popen([sys.executable, *arguments], stdout=output, stderr=error)
            processes.append((name, process))
            deadline = time.monotonic() + 45
            while not listening(port):
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"{name} 启动失败，请查看 {logs / (name + '.err.log')}")
                time.sleep(0.3)
        print("工作台：http://127.0.0.1:8010\nCtrl+C 停止本次启动的进程；Docker 和已有进程继续保留。", flush=True)
        while True:
            for name, process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f"{name} 已退出，请查看 data/runtime-logs")
            time.sleep(1)
    except KeyboardInterrupt:
        print("正在停止本次启动的服务……", flush=True)
    finally:
        for _, process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for _, process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
