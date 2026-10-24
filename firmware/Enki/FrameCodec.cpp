#include "FrameCodec.h"
#define MINIZ_HEADER_FILE_ONLY
#include <graphics/pngle/miniz.c>

bool inflateFrame(uint8_t *output, size_t outputSize, const uint8_t *input, size_t inputSize) {
  // The convenience wrapper puts its ~11 KB decoder on the stack.
  // Arduino's loop stack is only 8 KB. Keep the matching decoder on the heap.
  static tinfl_decompressor *decoder = (tinfl_decompressor *)malloc(sizeof(tinfl_decompressor));
  if (!decoder)
    return false;
  tinfl_init(decoder);
  size_t produced = outputSize, consumed = inputSize;
  tinfl_status result = tinfl_decompress(decoder, input, &consumed, output, output,
      &produced, TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF);
  return result == TINFL_STATUS_DONE && produced == outputSize && consumed == inputSize;
}
