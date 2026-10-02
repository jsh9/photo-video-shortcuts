"""
Apple's HDR color profile: an iPhone HEIC with an ISO 21496-1 gain map also
holds an ICC profile for the HDR rendition (Display P3 with PQ, plus the tone
curve Apple derives from the gain map, in an 'hdgm' tag), on the 'tmap' item or
the gain map. Apple dims the HDR photo with that curve on screens that can't
show all of it, and on SDR screens. The JPEG XL keeps the profile byte for
byte, so Apple shows it like the original; its pixels stay the same. Profiles
that don't describe the pixels are ignored. Either way, a photo without a
usable profile gets a note, since its JXL may look slightly darker.

The test profiles are libjxl's own (written by djxl), with a placeholder 'hdgm'
tag: these tests check that the profile is carried over, not how Apple uses the
curve. One is reshaped like Apple's (photo_helpers.apple_shaped_hdr_profile),
whose A2B0 tag skcms, libjxl's color engine in WebAssembly, rejects.
"""

import numpy as np
import photo_helpers as ph
import pytest

CURVE = b'hdgm' + bytes(4) + bytes(range(256))  # placeholder tag data

P3_PQ, REC2020_PQ = 'RGB_D65_DCI_Rel_PeQ', 'RGB_D65_202_Rel_PeQ'
# name: (test photo, [(item holding a profile, the profile's color space as
# djxl names it, its 'hdgm' tag data or None)]); the last profile is the one
# kept, or the reason for the note
VARIANTS = {
    'tmap': ('heic_hdr', [('tmap', P3_PQ, CURVE)]),
    # with tags like Apple's (iOS 26), some of which skcms rejects
    'apple_shaped': ('heic_hdr', [('tmap', P3_PQ, CURVE)]),
    'gain_map': ('heic_hdr', [('gain map', P3_PQ, CURVE)]),
    # the tmap's profile is in another color space; the gain map's is used
    'second_profile': (
        'heic_hdr',
        [('tmap', REC2020_PQ, CURVE), ('gain map', P3_PQ, CURVE)],
    ),
    # ignored: no tone curve
    'no_curve': ('heic_hdr', [('tmap', P3_PQ, None)]),
    # ignored: another color space than the pixels'
    'rec2020': ('heic_hdr', [('tmap', REC2020_PQ, CURVE)]),
    'sdr': ('heic_hdr', [('tmap', 'RGB_D65_SRG_Rel_SRG', CURVE)]),
    'srgb_photo': ('heic_hdr_srgb', [('tmap', P3_PQ, CURVE)]),
}
KEPT = ['tmap', 'apple_shaped', 'gain_map', 'second_profile']
# reshaped like Apple's HDR profile
APPLE_SHAPED = {'apple_shaped'}
IGNORED = sorted(set(VARIANTS) - set(KEPT))


@pytest.fixture(scope='module')
def variants(photos, batch, tmp_path_factory):
    """
    The test photos with profiles added: {name: (heic, {item: profile})}, see
    VARIANTS.
    """
    folder = tmp_path_factory.mktemp('profiles')
    _, pq_jxl, _ = batch.results['heic_hdr']
    result = {}
    for name, (photo, added) in VARIANTS.items():
        assert ph.hdr_profile(photos[photo]) is None, (
            f'make_photo already wrote an HDR profile in {photo}'
        )
        heic, profiles = photos[photo], {}
        for i, (item, space, curve) in enumerate(added):
            icc = folder / f'{name}.icc'
            ph.run(
                [
                    'djxl',
                    pq_jxl,
                    folder / 'profile.ppm',
                    f'--color_space={space}',
                    f'--icc_out={icc}',
                ],
                check=True,
            )
            profile = icc.read_bytes()
            if name in APPLE_SHAPED:
                profile = ph.apple_shaped_hdr_profile(profile, curve)
            elif curve:
                profile = ph.add_icc_tag(profile, 'hdgm', curve)

            out = folder / f'{photo}_{name}_{i}.heic'
            ph.with_item_profile(heic, item, profile, out)
            heic, profiles[item] = out, profile

        result[name] = (heic, profiles)

    return result


def last_profile(variants, name):
    """The profile added last: the one kept, or the reason for the note."""
    item = VARIANTS[name][1][-1][0]
    return variants[name][1][item]


@pytest.fixture(scope='module')
def converted(wasm, variants, tmp_path_factory):
    """
    The variants converted in one batch at quality 83: {name: (jxl, what
    jxlbatch printed for it)}.
    """
    folder = tmp_path_factory.mktemp('converted')
    staged = ph.stage(folder, [heic for heic, _ in variants.values()])
    result = wasm.run(['-q', '83', '-e', '7', 'jxl_job.txt'], folder)
    assert result.returncode == 0, result.stdout + result.stderr
    done = ph.read_done(folder)
    out = {}
    for index, heic in staged.items():
        name = next(n for n, (h, _) in variants.items() if h == heic)
        jxl, _ = done[index]
        out[name] = (jxl, ph.photo_output(result.stdout, heic.stem))

    return out


def plain(batch, name):
    """The JPEG XL of the same test photo without the added profile."""
    _, jxl, _ = batch.results[VARIANTS[name][0]]
    return jxl


def decode(jxl, ppm):
    """16-bit Display P3 PQ pixels, as djxl decodes them."""
    ph.run(['djxl', jxl, ppm, '--color_space=RGB_D65_DCI_Rel_PeQ'], check=True)
    return ph.read_ppm(ppm)[0]


@pytest.mark.parametrize('name', sorted(VARIANTS))
def test_variant_has_the_profiles(variants, name):
    heic, profiles = variants[name]
    for item, profile in profiles.items():
        assert ph.item_profile(heic, item) == profile


@pytest.mark.parametrize('name', KEPT)
def test_profile_is_kept(variants, converted, name, tmp_path):
    profile = last_profile(variants, name)
    jxl, output = converted[name]
    assert ph.jxl_profile(jxl, tmp_path) == profile
    assert 'lossy' in ph.run(['jxlinfo', jxl], check=True).stdout
    assert ', HDR ' in output
    assert '!' not in output


@pytest.mark.parametrize('name', KEPT)
def test_pixels_are_unchanged(batch, converted, name, tmp_path):
    jxl, _ = converted[name]
    ours = decode(jxl, tmp_path / 'ours.ppm')
    without = decode(plain(batch, name), tmp_path / 'without.ppm')
    np.testing.assert_array_equal(ours, without)


@pytest.mark.parametrize('name', KEPT)
def test_profile_costs_at_most_its_size(batch, variants, converted, name):
    profile = last_profile(variants, name)
    jxl, _ = converted[name]
    growth = jxl.stat().st_size - plain(batch, name).stat().st_size
    assert 0 < growth <= len(profile)


@pytest.mark.parametrize('name', IGNORED)
def test_unsuitable_profile_is_ignored(batch, converted, name):
    jxl, output = converted[name]
    assert jxl.read_bytes() == plain(batch, name).read_bytes()
    # said, since the JXL may look slightly darker than the original
    output = ' '.join(output.split())
    if VARIANTS[name][1][-1][2] is None:
        assert "Apple's HDR profile not found" in output
    else:
        assert "Apple's HDR profile not used (unrecognized format)" in output


@pytest.mark.parametrize('name', ['heic_hdr', 'heic_hdr_srgb'])
def test_photo_without_profile_says_so(batch, name):
    original, _, _ = batch.results[name]
    output = ' '.join(ph.photo_output(batch.output, original.stem).split())
    assert "Apple's HDR profile not found" in output


@pytest.mark.parametrize('name', ['tmap', 'apple_shaped'])
def test_every_build(encoder, variants, photos, apple_hdr, name, tmp_path):
    heic = variants[name][0]
    profile = last_profile(variants, name)
    ph.stage(tmp_path, [heic])
    result = encoder.run(['jxl_job.txt'], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '!' not in ph.photo_output(result.stdout, heic.stem)
    jxl = tmp_path / 'jxl_out_1.jxl'
    assert ph.jxl_profile(jxl, tmp_path) == profile
    ours = ph.jxl_hdr_pixels(jxl, tmp_path / 'hdr.ppm')
    apple = apple_hdr(photos['heic_hdr'])
    assert ours.shape == apple.shape
    assert ph.pq_psnr(apple, ours) >= ph.MIN_PQ_PSNR
