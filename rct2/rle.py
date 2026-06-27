"""RCT2 run-length encoding.

Control byte `c`:
  c < 128  → next (c + 1) bytes are literal
  c >= 128 → next byte is repeated (257 - c) times
"""


def decompress(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        i += 1
        if c < 128:
            count = c + 1
            out.extend(data[i:i + count])
            i += count
        else:
            count = 257 - c
            out.extend(data[i:i + 1] * count)
            i += 1
    return bytes(out)


def compress(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        run = 1
        while i + run < n and run < 129 and data[i + run] == data[i]:
            run += 1

        if run >= 3:
            out.append(257 - run)
            out.append(data[i])
            i += run
        else:
            start = i
            while i < n and (i - start) < 128:
                if (i + 2 < n
                        and data[i] == data[i + 1]
                        and data[i + 1] == data[i + 2]):
                    break
                i += 1
            length = i - start
            out.append(length - 1)
            out.extend(data[start:i])
    return bytes(out)
