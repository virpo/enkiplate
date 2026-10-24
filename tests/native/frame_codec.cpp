#include "FrameCodec.h"
#include <cassert>
#include <fstream>
#include <iterator>
#include <vector>

std::vector<uint8_t> read(const char *path) {
  std::ifstream stream(path, std::ios::binary);
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(stream), {});
}
int main(int argc, char **argv) {
  assert(argc == 3);
  auto compressed = read(argv[1]), raw = read(argv[2]);
  assert(raw.size() == 180000 && !compressed.empty());
  std::vector<uint8_t> decoded(raw.size());
  assert(inflateFrame(decoded.data(), decoded.size(), compressed.data(), compressed.size()));
  assert(decoded == raw);
  assert(!inflateFrame(decoded.data(), decoded.size(), compressed.data(), compressed.size() - 1));
  assert(!inflateFrame(decoded.data(), decoded.size() - 1, compressed.data(), compressed.size()));
  compressed.back() ^= 1;
  assert(!inflateFrame(decoded.data(), decoded.size(), compressed.data(), compressed.size()));
}
