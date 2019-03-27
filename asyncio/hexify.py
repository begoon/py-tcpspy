class Hexify:
    def __init__(self, width):
        self.padding = ''.rjust(19, '.')
        self.printables = [self.printable(x) for x in range(256)]
        self.width = width

    def printable(self, ch):
       if ch < 32 or ch > 127:
           return '.'
       return chr(ch)

    def header(self):
        yield f"{self.padding} ######  {'.'.join(map(lambda x: '%02X' % x, range(self.width)))}\n"
        yield f"{self.padding} ------  {''.ljust(self.width*3-1, '-')}\n"

    def reset(self):
        self.offset = -self.width

    def hexify_chunk(self, chunk):
        dump = " ".join(map(lambda x: f"{x:02X}", chunk))
        char = "".join(map(lambda x: self.printables[x], chunk))
        self.offset += self.width
        return "%s %06X: %-*s  %-*s\n" % (self.padding, self.offset, self.width*3, dump, self.width, char)

    def hexify_chunks(self, raw):
        for i in range(0, len(raw), self.width):
            yield self.hexify_chunk(raw[i:i + self.width])

    def hexify_data(self, raw):
        self.reset()
        yield from self.hexify_chunks(raw)
        
    def hexify(self, raw):
        yield from self.header()
        yield from self.hexify_data(raw)
