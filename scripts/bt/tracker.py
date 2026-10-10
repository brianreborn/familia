#!/usr/bin/env python3
"""Minimal private BitTorrent HTTP tracker PoC (BEP 3 + BEP 23 compact).

Private: only infohashes that have a <hex>.torrent in --allow-dir are tracked;
anything else gets a failure reason. Bind must be loopback or a LAN address
(validate_graph.py enforces this for graph transports).

  tracker.py --bind 192.168.1.9 --port 6969 --allow-dir ~/.familia/bt/torrents
"""
import argparse, ipaddress, os, socket, struct, sys, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bencode import enc
PEERS, TTL = {}, 1800

class H(BaseHTTPRequestHandler):
    def reply(s, d):
        b = enc(d); s.send_response(200); s.send_header("Content-Type", "text/plain")
        s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
    def do_GET(s):
        u = urllib.parse.urlsplit(s.path)
        if u.path != "/announce": s.send_error(404); return
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True, encoding="latin-1")
        ih = q.get("info_hash", [""])[0].encode("latin-1")
        if len(ih) != 20: return s.reply({"failure reason": "bad info_hash"})
        hx = ih.hex()
        if not os.path.isfile(os.path.join(s.server.allow, hx + ".torrent")):
            return s.reply({"failure reason": "unregistered torrent (private tracker)"})
        try: port = int(q["port"][0])
        except Exception: return s.reply({"failure reason": "bad port"})
        ip = q.get("ip", [s.client_address[0]])[0]
        try: ipaddress.IPv4Address(ip)
        except ValueError: ip = s.client_address[0]
        peers = PEERS.setdefault(hx, {}); now = time.time()
        for k in [k for k, (_, t) in peers.items() if now - t > TTL]: del peers[k]
        key = (ip, port)
        if q.get("event", [""])[0] == "stopped": peers.pop(key, None)
        else: peers[key] = (q.get("left", ["1"])[0] == "0", now)
        others = [k for k in peers if k != key]
        comp = b"".join(socket.inet_aton(i) + struct.pack(">H", p) for i, p in others)
        seeders = sum(1 for v in peers.values() if v[0])
        print(f"announce {hx[:12]} {ip}:{port} ev={q.get('event',[''])[0]} peers={len(peers)}", flush=True)
        s.reply({"interval": 30, "min interval": 10, "complete": seeders, "incomplete": len(peers) - seeders, "peers": comp})
    def log_message(s, *a): pass

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--bind", required=True); ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--allow-dir", required=True); o = ap.parse_args()
    a = ipaddress.ip_address(o.bind)
    if a.is_unspecified or not (a.is_private or a.is_loopback): sys.exit(f"tracker: refusing to bind non-LAN address {o.bind}")
    srv = ThreadingHTTPServer((o.bind, o.port), H); srv.allow = os.path.expanduser(o.allow_dir)
    os.makedirs(srv.allow, exist_ok=True)
    print(f"tracker on http://{o.bind}:{o.port}/announce allow-dir={srv.allow}", flush=True); srv.serve_forever()

if __name__ == "__main__": main()
