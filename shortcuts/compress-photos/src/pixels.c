#include "pixels.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_ONLY_JPEG
#define STBI_NO_STDIO
#define STBI_NO_LINEAR
#define STBI_NO_HDR
#define STBI_NO_THREAD_LOCALS
#include "../third_party/stb_image.h"

int stb_decode(const uint8_t *buf, size_t len, image_t *img, char *err, size_t err_len) {
  memset(img, 0, sizeof *img);
  if (len > INT_MAX) {
    snprintf(err, err_len, "file too large");
    return -1;
  }
  int w = 0, h = 0, comp = 0;
  if (!stbi_info_from_memory(buf, (int)len, &w, &h, &comp)) {
    snprintf(err, err_len, "unreadable image (%s)", stbi_failure_reason());
    return -1;
  }
  const int is16 = stbi_is_16_bit_from_memory(buf, (int)len);
  void *px = is16 ? (void *)stbi_load_16_from_memory(buf, (int)len, &w, &h, &comp, 0)
                  : (void *)stbi_load_from_memory(buf, (int)len, &w, &h, &comp, 0);
  if (!px) {
    snprintf(err, err_len, "decoding failed (%s)", stbi_failure_reason());
    return -1;
  }
  img->data = (uint8_t *)px;
  img->w = (uint32_t)w;
  img->h = (uint32_t)h;
  img->channels = comp;
  img->bytes_per_sample = is16 ? 2 : 1;
  img->bits = is16 ? 16 : 8;
  img->stride = (size_t)w * pixel_size(img);
  return 0;
}

size_t pixel_size(const image_t *img) {
  return (size_t)img->channels * (size_t)img->bytes_per_sample;
}

void image_free(image_t *img) {
  if (img->owner) {
    img->owner_free(img->owner);
  } else {
    free(img->data);  // stb_image allocates with malloc
  }
  img->data = NULL;
  img->owner = NULL;
  img->render = NULL;
}

void color_free(color_t *color) {
  free(color->icc.data);
  free(color->hdr_icc.data);
  memset(color, 0, sizeof *color);
}

int image_make_packed(image_t *img) {
  const size_t row = (size_t)img->w * pixel_size(img);
  if (!img->owner && img->stride == row) return 0;
  uint8_t *packed = (uint8_t *)malloc(row * img->h);
  if (!packed) return -1;
  if (img->render) {
    if (img->render(img->owner, 0, 0, img->w, img->h, packed, row) != 0) {
      free(packed);
      return -1;
    }
  } else {
    for (uint32_t y = 0; y < img->h; y++) memcpy(packed + y * row, img->data + y * img->stride, row);
  }
  image_free(img);
  img->data = packed;
  img->stride = row;
  return 0;
}

void image_crop(image_t *img, uint32_t left, uint32_t top, uint32_t w, uint32_t h) {
  const size_t ps = pixel_size(img);
  uint8_t *src = img->data + (size_t)top * img->stride + (size_t)left * ps;
  if (img->owner) {
    img->data = src;  // a view: the owner frees the pixels
  } else {
    // image_free frees `data`, so the rows move to the start of the buffer
    const size_t row = (size_t)w * ps;
    for (uint32_t y = 0; y < h; y++) memmove(img->data + (size_t)y * row, src + (size_t)y * img->stride, row);
    img->stride = row;
  }
  img->w = w;
  img->h = h;
}

int image_drop_opaque_alpha(image_t *img) {
  const int c = img->channels;
  if ((c != 2 && c != 4) || img->render) return 0;
  const uint32_t amax = (1u << img->bits) - 1;
  for (uint32_t y = 0; y < img->h; y++) {
    const uint8_t *row = img->data + y * img->stride;
    for (uint32_t x = 0; x < img->w; x++) {
      const uint32_t a = img->bytes_per_sample == 1 ? row[x * c + c - 1]
                                                    : ((const uint16_t *)row)[x * c + c - 1];
      if (a < amax) return 0;
    }
  }
  if (image_make_packed(img) != 0) return 0;
  const size_t n = (size_t)img->w * img->h;
  const size_t in_ps = (size_t)c * img->bytes_per_sample;
  const size_t out_ps = (size_t)(c - 1) * img->bytes_per_sample;
  for (size_t i = 0; i < n; i++) memmove(img->data + i * out_ps, img->data + i * in_ps, out_ps);
  img->channels = c - 1;
  img->stride = (size_t)img->w * out_ps;
  uint8_t *shrunk = (uint8_t *)realloc(img->data, n * out_ps);
  if (shrunk) img->data = shrunk;
  return 1;
}

static inline void copy_px(uint8_t *d, const uint8_t *s, size_t ps) {
  if (ps == 3) {
    d[0] = s[0];
    d[1] = s[1];
    d[2] = s[2];
  } else if (ps == 4) {
    memcpy(d, s, 4);
  } else {
    memcpy(d, s, ps);
  }
}

// Fills dst (W x H) tile by tile; SX/SY give the source pixel for (x, y).
#define TILE 64
#define ORIENT_LOOP(SX, SY)                                                  \
  for (uint32_t ty = 0; ty < H; ty += TILE) {                                \
    const uint32_t ye = H - ty > TILE ? ty + TILE : H;                       \
    for (uint32_t tx = 0; tx < W; tx += TILE) {                              \
      const uint32_t xe = W - tx > TILE ? tx + TILE : W;                     \
      for (uint32_t y = ty; y < ye; y++) {                                   \
        uint8_t *d = dst + ((size_t)y * W + tx) * ps;                        \
        for (uint32_t x = tx; x < xe; x++, d += ps) {                        \
          copy_px(d, src + (size_t)(SY) * sstride + (size_t)(SX) * ps, ps);  \
        }                                                                    \
      }                                                                      \
    }                                                                        \
  }

int image_orient(image_t *img, int o) {
  if (o < 2 || o > 8) return 0;
  if (img->render && image_make_packed(img) != 0) return -1;
  const uint32_t w = img->w, h = img->h;
  const size_t ps = pixel_size(img), sstride = img->stride;
  const int swap = o >= 5;
  const uint32_t W = swap ? h : w, H = swap ? w : h;
  uint8_t *dst = (uint8_t *)malloc((size_t)W * H * ps);
  if (!dst) return -1;
  const uint8_t *src = img->data;
  // EXIF orientation: how the stored image must be transformed for display.
  switch (o) {
    case 2: ORIENT_LOOP(w - 1 - x, y) break;              // mirror horizontal
    case 3: ORIENT_LOOP(w - 1 - x, h - 1 - y) break;      // rotate 180
    case 4: ORIENT_LOOP(x, h - 1 - y) break;              // mirror vertical
    case 5: ORIENT_LOOP(y, x) break;                      // transpose
    case 6: ORIENT_LOOP(y, h - 1 - x) break;              // rotate 90 CW
    case 7: ORIENT_LOOP(w - 1 - y, h - 1 - x) break;      // transverse
    default: ORIENT_LOOP(w - 1 - y, x) break;             // 8: rotate 90 CCW
  }
  image_free(img);
  img->data = dst;
  img->w = W;
  img->h = H;
  img->stride = (size_t)W * ps;
  return 0;
}
