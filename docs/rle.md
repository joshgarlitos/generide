# RLE

RCT2's RLE format has two modes.

A bit is the smallest unit of data in a computer. It can only be one of two values: 0 or 1. A byte is a group of 8 bits. Because each bit has two possible values and you have 8 of them, the total number of combinations is 2⁸, which is 256. So a byte can represent any number from 0 to 255.

When you see `0x03`, that's just the number 3 written in hexadecimal, a base-16 counting system programmers use because it maps cleanly onto how computers store data. `0x03` means 3. `0xFD` means 253. Everything in a binary file is a sequence of bytes, so everything in a binary file is a sequence of numbers between 0 and 255.

The first byte of each chunk is a control byte, called `c`. Its value tells the decoder what to do with the bytes that follow.

If `c` is below 128, you're in a literal run. The next `c + 1` bytes are raw data, copied straight to output. So if `c` is 3, the next four bytes are literals.

If `c` is 128 or above, you're in a repeat run. The next single byte gets repeated `257 - c` times. So if `c` is 253, that one byte gets repeated four times.

The decoder walks the stream one control byte at a time, picks a mode, emits the bytes, and moves on.

Compression inverts that. It scans forward from the current position, counts identical bytes in a row, and decides: three or more identical bytes get a repeat run; anything else accumulates into a literal chunk until it hits a run or the 128-byte limit.

One thing worth knowing: the same decompressed data can come from multiple valid compressed forms. Three identical bytes could be a repeat run or a three-byte literal chunk. Both decompress identically. So the round-trip test compares decompressed bytes rather than comparing compressed forms to each other.
