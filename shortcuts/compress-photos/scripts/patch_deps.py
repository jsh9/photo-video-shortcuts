#!/usr/bin/env python3
"""
Applies jxlbatch's small source edits to the dependency checkouts in .deps/.

Used by build-wasm.sh (``--wasi --skcms``) and build-macos.sh (``--skcms``).
Each edit is idempotent: a file that already has it is left alone, and a file
whose expected code is missing stops the build, so a dependency upgrade can't
silently skip a patch.

- ``--wasi``: WASI (the non-threads target) has no threads, no C++ exceptions
  and no mkstemp. libjxl drops its hard pthreads dependency (the same edit as
  gen2brain/jpegxl); libheif decodes on the calling thread, skips its
  exception wrapper and its temporary files (only used when writing HEIF).
  The libheif edits are guarded by ``__wasi__`` or ``__cpp_exceptions``, so a
  native build of the same checkout is unaffected.
- ``--skcms``: lets skcms, libjxl's color engine in these builds, read Apple's
  HDR profile (see DEVELOPING.md, HDR).

Usage::

    patch_deps.py [--wasi] [--skcms] --libjxl DIR [--libheif DIR]
"""

import argparse
import pathlib
import sys


def replace(root, rel, old, new):
    path = root / rel
    text = path.read_text()
    if new in text:
        return

    if old not in text:
        sys.exit(
            f'{root.name}/{rel}: expected code not found; check the patch for this version'
        )

    path.write_text(text.replace(old, new, 1))
    print(f'patched {root.name}/{rel}')


def patch_wasi(libjxl, libheif):
    # libjxl: drop the hard pthreads dependency (as gen2brain/jpegxl does).
    for rel, lines in {
        'CMakeLists.txt': [
            'set(THREADS_PREFER_PTHREAD_FLAG YES)',
            'find_package(Threads REQUIRED)',
        ],
        'lib/CMakeLists.txt': ['include(jxl_threads.cmake)'],
        'lib/jxl.cmake': ['  Threads::Threads'],
        'lib/jpegli.cmake': ['  Threads::Threads'],
    }.items():
        path = libjxl / rel
        text = path.read_text()
        new = '\n'.join(
            line for line in text.split('\n') if line.rstrip() not in lines
        )
        if new != text:
            path.write_text(new)
            print(f'patched libjxl/{rel}')

    # libheif: temp files are only used when writing HEIF; WASI has no mkstemp.
    replace(
        libheif,
        'libheif/box.cc',
        '#if !defined(_WIN32)\n    strcpy(m_tmp_filename, "/tmp/libheif-XXXXXX");',
        '#if defined(__wasi__)\n    m_use_tmpfile = false;  // WASI has no mkstemp; only used when writing files\n'
        '#elif !defined(_WIN32)\n    strcpy(m_tmp_filename, "/tmp/libheif-XXXXXX");',
    )
    # libheif: without exceptions, run the API body directly (failures abort).
    replace(
        libheif,
        'libheif/api_structs.h',
        'static inline heif_error exception_guard(F&& body) noexcept\n{\n  try {',
        'static inline heif_error exception_guard(F&& body) noexcept\n{\n#if !defined(__cpp_exceptions)\n'
        '  return body();  // built with -fno-exceptions (WASI): failures abort instead\n#else\n  try {',
    )
    replace(
        libheif,
        'libheif/api_structs.h',
        '  catch (...) {\n    return heif_error_internal_exception;\n  }\n}',
        '  catch (...) {\n    return heif_error_internal_exception;\n  }\n#endif\n}',
    )
    # libheif: file.cc includes, but doesn't use, the C++ wrapper, which throws.
    replace(
        libheif,
        'libheif/file.cc',
        '#include "libheif/heif_cxx.h"\n',
        '#if defined(__cpp_exceptions)  // unused here; its wrappers throw\n#include "libheif/heif_cxx.h"\n#endif\n',
    )
    # libheif: decode on the calling thread (libde265 supports 0 worker
    # threads), keeping deblocking and SAO, unlike the Emscripten branch.
    replace(
        libheif,
        'libheif/plugins/decoder_libde265.cc',
        '#else\n  int nThreads = (options->num_threads ? options->num_threads : 1);',
        '#elif defined(__wasi__)\n  // WASI has no threads: libde265 decodes on the calling thread (0 workers),\n'
        '  // keeping deblocking and SAO (unlike the Emscripten branch above).\n#else\n'
        '  int nThreads = (options->num_threads ? options->num_threads : 1);',
    )


# skcms (libjxl's pinned copy): Apple's HDR profile (iPhone photos, iOS 26) is
# PQ by its 'cicp' tag, but its A2B0 tag is an 'mAB ' without B curves, which
# skcms rejects, and with it the whole profile, before reading the 'cicp' tag.
# libjxl takes a PQ profile's color from that tag alone and transforms with a
# profile of its own, so the tag is read first, and a PQ profile is accepted
# without the A2B0/B2A0 tags skcms can't read.
SKCMS = 'third_party/skcms/skcms.cc'


def patch_skcms(libjxl):
    replace(
        libjxl,
        SKCMS,
        '    for (int i = 0; i < priorities; i++) {\n'
        '        // enum { perceptual, relative_colormetric, saturation }\n'
        '        if (priority[i] < 0 || priority[i] > 2) {\n'
        '            return false;\n'
        '        }\n'
        '        uint32_t sig = skcms_Signature_A2B0',
        '    skcms_ICCTag cicp_tag;\n'
        '    if (skcms_GetTagBySignature(profile, skcms_Signature_CICP, &cicp_tag)) {\n'
        '        if (!read_cicp(&cicp_tag, &profile->CICP)) {\n'
        '            // Malformed CICP tag\n'
        '            return false;\n'
        '        }\n'
        '        profile->has_CICP = true;\n'
        '    }\n'
        "    // jxlbatch: Apple's HDR profile is PQ by its 'cicp' tag, with A2B0/B2A0\n"
        "    // tags skcms rejects ('mAB ' without B curves). libjxl takes a PQ\n"
        "    // profile's color from the 'cicp' tag alone and never transforms with it.\n"
        '    const bool hdr_by_cicp = profile->has_CICP &&\n'
        '                             profile->CICP.transfer_characteristics == 16;\n'
        '\n'
        '    for (int i = 0; i < priorities; i++) {\n'
        '        // enum { perceptual, relative_colormetric, saturation }\n'
        '        if (priority[i] < 0 || priority[i] > 2) {\n'
        '            return false;\n'
        '        }\n'
        '        uint32_t sig = skcms_Signature_A2B0',
    )
    replace(
        libjxl,
        SKCMS,
        '            if (!read_a2b(&tag, &profile->A2B, pcs_is_xyz)) {\n'
        '                // Malformed A2B tag\n',
        '            if (!read_a2b(&tag, &profile->A2B, pcs_is_xyz)) {\n'
        "                if (hdr_by_cicp) break;  // jxlbatch: Apple's HDR profile\n"
        '                // Malformed A2B tag\n',
    )
    replace(
        libjxl,
        SKCMS,
        '            if (!read_b2a(&tag, &profile->B2A, pcs_is_xyz)) {\n'
        '                // Malformed B2A tag\n',
        '            if (!read_b2a(&tag, &profile->B2A, pcs_is_xyz)) {\n'
        "                if (hdr_by_cicp) break;  // jxlbatch: Apple's HDR profile\n"
        '                // Malformed B2A tag\n',
    )
    # the 'cicp' tag's original place (read above now)
    replace(
        libjxl,
        SKCMS,
        '    skcms_ICCTag cicp_tag;\n'
        '    if (skcms_GetTagBySignature(profile, skcms_Signature_CICP, &cicp_tag)) {\n'
        '        if (!read_cicp(&cicp_tag, &profile->CICP)) {\n'
        '            // Malformed CICP tag\n'
        '            return false;\n'
        '        }\n'
        '        profile->has_CICP = true;\n'
        '    }\n'
        '\n'
        '    return usable_as_src(profile);\n',
        '    return usable_as_src(profile) || hdr_by_cicp;\n',
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('--wasi', action='store_true', help='the WASI edits')
    ap.add_argument('--skcms', action='store_true', help='the skcms edit')
    ap.add_argument('--libjxl', type=pathlib.Path, required=True)
    ap.add_argument('--libheif', type=pathlib.Path)
    args = ap.parse_args()
    if args.wasi:
        if not args.libheif:
            ap.error('--wasi needs --libheif')

        patch_wasi(args.libjxl, args.libheif)

    if args.skcms:
        patch_skcms(args.libjxl)


if __name__ == '__main__':
    main()
