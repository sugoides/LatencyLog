import subprocess
import re
import threading
import time
import logging
import os

class NmapTracer:
    def __init__(self, database):
        self.db = database
        self.stop_event = threading.Event()
        self.threads = []
        self._hop_regex = re.compile(r"(\d+)\s+([<\d.]+)\s+ms\s+(.+)")

    def run_trace(self, server, port=443):
        """Executes a single nmap traceroute and returns the trace_id."""
        try:
            port = int(port) if port else 443
            cmd = ["nmap", "-Pn", "--traceroute", "-p", str(port), server]
            
            # Windows-specific: Prevent console window from flashing
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NO_WINDOW

            proc = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True,
                creationflags=creation_flags
            )
            stdout, _ = proc.communicate()
            
            hops = self._parse_output(stdout)
            status = "Success" if hops else "No Hops Found"
            return self.db.add_trace(server, port, status, hops)
        except Exception as e:
            logging.error(f"Trace failed for {server}: {e}")
            return None

    def _parse_output(self, output):
        hops = []
        in_section = False
        for line in output.splitlines():
            line = line.strip()
            if "TRACEROUTE" in line:
                in_section = True
                continue
            if in_section:
                match = self._hop_regex.search(line)
                if match:
                    hops.append({
                        'index': int(match.group(1)),
                        'rtt': float(match.group(2).replace('<', '')),
                        'address': match.group(3).strip()
                    })
        return hops

    def start_monitoring(self, servers, interval=30):
        def loop(srv):
            while not self.stop_event.is_set():
                self.run_trace(srv['server'], srv['port'])
                for _ in range(interval):
                    if self.stop_event.is_set(): break
                    time.sleep(1)

        for s in servers:
            t = threading.Thread(target=loop, args=(s,), daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=1)
        self.threads = []
        self.stop_event.clear()
