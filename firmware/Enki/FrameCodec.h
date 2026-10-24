#pragma once
#include <stddef.h>
#include <stdint.h>

// Separate translation unit, using the pinned Inkplate decoder's own ABI.
bool inflateFrame(uint8_t *output, size_t outputSize, const uint8_t *input, size_t inputSize);
