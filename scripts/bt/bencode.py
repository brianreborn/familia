"""Minimal bencode (BEP 3)."""
def enc(x):
    if isinstance(x, int): return b"i%de" % x
    if isinstance(x, str): x = x.encode()
    if isinstance(x, bytes): return b"%d:%s" % (len(x), x)
    if isinstance(x, list): return b"l" + b"".join(map(enc, x)) + b"e"
    if isinstance(x, dict): return b"d" + b"".join(enc(k) + enc(v) for k, v in sorted((k.encode() if isinstance(k, str) else k, v) for k, v in x.items())) + b"e"
    raise TypeError(type(x))
def dec(b, i=0):
    c = b[i:i+1]
    if c == b"i": j = b.index(b"e", i); return int(b[i+1:j]), j + 1
    if c in (b"l", b"d"):
        i += 1; out = [] if c == b"l" else {}
        while b[i:i+1] != b"e":
            if c == b"l": v, i = dec(b, i); out.append(v)
            else: k, i = dec(b, i); v, i = dec(b, i); out[k] = v
        return out, i + 1
    j = b.index(b":", i); n = int(b[i:j]); return b[j+1:j+1+n], j + 1 + n
def loads(b): return dec(b)[0]
