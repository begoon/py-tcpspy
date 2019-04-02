class Hexify:
    def __init__(self, width):
        self.width = width
        self.printables = list(map(self.printable, range(256)))
        self.padding_prefix = '.' * 19
        self.padding_legend = '.'.join(map("{:02X}".format, range(self.width)))
        self.padding_separator = '-' * (self.width*3-1)
        self.hex = list(map("{:02X} ".format, range(256)))

    def printable(self, c):
       return chr(c) if 32 <= c < 128 else '.'

    def header(self):
        yield f"{self.padding_prefix} ######  {self.padding_legend}\n"
        yield f"{self.padding_prefix} ------  {self.padding_separator}\n"

    def reset(self):
        self.offset = -self.width

    def hexify_chunk(self, chunk):
        dump = "".join(map(lambda x: self.hex[x], chunk))
        char = "".join(map(lambda x: self.printables[x], chunk))
        self.offset += self.width
        return "%s %06X: %-*s  %-*s\n" % (self.padding_prefix, self.offset, self.width*3, dump, self.width, char)

    def hexify_chunks(self, raw):
        for i in range(0, len(raw), self.width):
            yield self.hexify_chunk(raw[i:i + self.width])

    def hexify_data(self, raw):
        self.reset()
        yield from self.hexify_chunks(raw)
        
    def hexify(self, raw):
        yield from self.header()
        yield from self.hexify_data(raw)
