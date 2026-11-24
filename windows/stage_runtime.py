"""Stage pinned FFmpeg binaries and record dependency provenance for the installer."""

import hashlib
from importlib import metadata
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parent.parent
NOTICE = re.compile(r'^(licen[sc]e|copying|notice|credits)', re.IGNORECASE)
OPENCV_VERSION = '4.7.0.72'
OPENCV_PLUGIN_SHA256 = '3552d34215ba2ea22ce68c54b0bee03b857610ebc30e102f6c982b3e415a159c'
OPENCV_IPP_ARCHIVE = (
    'https://raw.githubusercontent.com/opencv/opencv_3rdparty/'
    'a56b6ac6f030c312b2dce17430eef13aed9af274/ippicv/ippicv_2020_win_intel64_20191018_general.zip'
)
OPENCV_IPP_SHA256 = 'e64e09f8a2e121d4fff440fb12b1298bc0760f1391770aefe5d1deb6630352b7'
VC_RUNTIME = re.compile(r'^(?:vcruntime|msvcp|msvcr\d|concrt|vcomp|mfc).*\.dll$')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_archive(cache, url, checksum):
    archive = cache / url.rsplit('/', 1)[-1]
    if not archive.exists():
        partial = archive.with_suffix('.part')
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'PyMoviePrint-build'})
            with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            if sha256(partial) != checksum:
                raise ValueError(f'Downloaded archive does not match the pinned checksum: {url}')
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    elif sha256(archive) != checksum:
        raise ValueError(f'Cached archive does not match the pinned checksum: {archive}')
    return archive


def ffmpeg_runtime(app, cache, notices):
    pin = json.loads((ROOT / 'windows' / 'ffmpeg-runtime.json').read_bytes())
    archive = verified_archive(cache, pin['url'], pin['sha256'])
    media = app / 'ffmpeg'
    media.mkdir()
    license_target = notices / 'FFmpeg'
    license_target.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir():
                continue
            path = PurePosixPath(member.filename)
            if len(path.parts) == 3 and path.parts[1] == 'bin' and path.suffix.lower() in {'.exe', '.dll'}:
                target = media / path.name
            elif len(path.parts) == 2 and NOTICE.match(path.name):
                target = license_target / path.name
            else:
                continue
            # Copy only recognised flat names, never ZIP paths, into fresh directories.
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', target.name):
                raise ValueError(f'Unexpected archive member name: {member.filename}')
            with bundle.open(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
    if not list(media.glob('avcodec-*.dll')) or not list(license_target.iterdir()):
        raise ValueError('Expected a shared FFmpeg runtime and upstream licence notices.')
    versions = {}
    for name in ('ffmpeg', 'ffprobe', 'ffplay'):
        executable = media / f'{name}.exe'
        lines = subprocess.check_output([executable, '-version'], text=True, timeout=20).splitlines()
        if not lines or pin['source_commit'][:10] not in lines[0]:
            raise ValueError(f'{name} does not report the pinned FFmpeg source revision.')
        if not any('configuration:' in line for line in lines) or re.search(r'--enable-(gpl|nonfree)\b', '\n'.join(lines)):
            raise ValueError(f'{name} does not report an expected LGPL configuration.')
        versions[name] = lines
    license_output = subprocess.check_output(
        [media / 'ffmpeg.exe', '-L'], stderr=subprocess.PIPE, text=True, timeout=20,
    )
    if not re.search(r'GNU Lesser General Public License\b.{0,180}\bversion 3\b', ' '.join(license_output.split()), re.I):
        raise ValueError('The pinned FFmpeg build did not report the expected LGPLv3 licence.')
    (license_target / 'SOURCE.txt').write_text(
        f"FFmpeg uses the GNU LGPL. Exact FFmpeg source revision:\n"
        f"https://github.com/FFmpeg/FFmpeg/tree/{pin['source_commit']}\n"
        f"Distributor's build scripts and patches: {pin['build_recipe']}\n"
        f"Original binary archive: {pin['url']}\n"
        f"SHA-256: {pin['sha256']}\n", encoding='utf-8',
    )
    return {
        **pin,
        'reported_license': 'LGPL-3.0-or-later',
        'executables_and_libraries': {path.name: sha256(path) for path in sorted(media.iterdir())},
        'tool_versions': versions,
    }


def python_notices(notices):
    packages = []
    for dist in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
        name = dist.metadata['Name']
        package_notices = []
        for path in dist.files or ():
            if not NOTICE.match(path.name) or '..' in path.parts:
                continue
            source = dist.locate_file(path)
            if not source.is_file():
                continue
            target = notices / name / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            package_notices.append(target.relative_to(notices).as_posix())
        packages.append({
            'name': name,
            'version': dist.version,
            'declared_license': dist.metadata.get('License-Expression') or dist.metadata.get('License'),
            'notices': package_notices,
        })
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, notices / 'Python-LICENSE.txt')
    for library in ('tcl8.6', 'tk8.6'):
        license_path = Path(sys.base_prefix) / 'tcl' / library / 'license.terms'
        if license_path.is_file():
            shutil.copy2(license_path, notices / f'{library}-license.terms')
    return packages


def opencv_runtime(app, cache, notices):
    distribution = metadata.distribution('opencv-python')
    if distribution.version != OPENCV_VERSION:
        raise ValueError('Review OpenCV source provenance before updating the Windows wheel.')
    plugins = list(app.rglob('opencv_videoio_ffmpeg*.dll'))
    if len(plugins) != 1 or sha256(plugins[0]) != OPENCV_PLUGIN_SHA256:
        raise ValueError('Packaged OpenCV FFmpeg plugin does not match the audited upstream binary.')
    recipe = 'https://github.com/opencv/opencv_3rdparty/tree/7dd0d4f1d6fe75f05f3d3b5e38cbc96c1a2d2809/ffmpeg'
    source = {
        'wheel_build_scripts': 'https://github.com/opencv/opencv-python/tree/f9de34ec8bc8bc5d61e5e35c0721676993da7d71',
        'wheel_opencv_source': 'https://github.com/opencv/opencv/tree/725e440d278aca07d35a5e8963ef990572b07316',
        'plugin_build_scripts': recipe,
        'plugin_opencv_source': 'https://github.com/opencv/opencv/tree/4abe6dc48d4ec6229f332cc6cf6c7e234ac8027e',
        'plugin_ffmpeg_source': 'https://github.com/FFmpeg/FFmpeg/tree/n4.4.3',
        'plugin_aom_source': 'https://aomedia.googlesource.com/aom/+/refs/tags/v3.5.0',
        'plugin_libvpx_source': 'https://chromium.googlesource.com/webm/libvpx/+/refs/tags/v1.12.0',
        'plugin_openh264_headers': 'https://github.com/cisco/openh264/tree/v1.8.0/codec/api/svc',
    }
    package_notices = notices / 'opencv-python'
    (package_notices / 'SOURCE.txt').write_text(
        'OpenCV and its separate FFmpeg plugin source references from the upstream build recipe:\n'
        + ''.join(f'{component}: {url}\n' for component, url in source.items())
        + 'The source archives must accompany a public distribution.\n',
        encoding='utf-8',
    )
    # The Windows wheel reports static Intel IPP. Its redistribution terms
    # require reproducing the copyright and licence from this pinned package.
    ipp = verified_archive(cache, OPENCV_IPP_ARCHIVE, OPENCV_IPP_SHA256)
    ipp_notices = package_notices / 'Intel-IPP'
    ipp_notices.mkdir()
    with zipfile.ZipFile(ipp) as archive:
        for name in ('EULA.rtf', 'third-party-programs.txt'):
            (ipp_notices / name).write_bytes(archive.read(f'ippicv_win/{name}'))
    from cv2 import getBuildInformation

    (package_notices / 'BUILD.txt').write_text(getBuildInformation(), encoding='utf-8')
    return {
        'wheel_version': distribution.version,
        'plugin': plugins[0].relative_to(app).as_posix(),
        'plugin_sha256': OPENCV_PLUGIN_SHA256,
        'plugin_license': 'LGPL-2.1-or-later',
        'source_references': source,
        'build_information': 'licenses/opencv-python/BUILD.txt',
        'intel_ipp': {
            'archive': OPENCV_IPP_ARCHIVE,
            'sha256': OPENCV_IPP_SHA256,
            'notices': 'licenses/opencv-python/Intel-IPP',
        },
    }


def numpy_runtime(app):
    import numpy

    config = numpy.show_config(mode='dicts')
    dependencies = config['Build Dependencies']
    if (dependencies['blas'].get('found')
            or dependencies['lapack'].get('detection method') != 'internal'):
        raise ValueError('Expected NumPy with its internal BLAS and LAPACK fallback routines.')
    unwanted = [
        path.name for path in app.rglob('*.dll')
        if any(name in path.name.lower() for name in ('openblas', 'quadmath', 'gfortran'))
    ]
    if unwanted:
        raise ValueError(f'Unexpected external NumPy runtime files: {unwanted}')
    return {
        'version': numpy.__version__,
        'build_dependencies': dependencies,
        'source_sha256': None,
        'wheel_sha256': None,
    }


def windows_runtime(app):
    import pefile

    system_libraries = {}
    vc_libraries = {}
    vc_exports = {}
    for path in sorted(app.rglob('*.dll')):
        name = path.name.lower()
        if name == 'ucrtbase.dll' or name.startswith(('api-ms-win-', 'ext-ms-win-')):
            system_libraries[path.relative_to(app).as_posix()] = sha256(path)
            path.unlink()
        elif VC_RUNTIME.match(name):
            if name not in {'vcruntime140.dll', 'vcruntime140_1.dll'}:
                raise ValueError(f'Review the redistribution terms for this new runtime: {path.name}')
            source = Path(sys.base_prefix) / name
            digest = sha256(path)
            if not source.is_file() or digest != sha256(source):
                raise ValueError(f'{path.name} differs from the runtime supplied with the build Python.')
            with pefile.PE(str(path), fast_load=True) as binary:
                if binary.FILE_HEADER.Machine != 0x8664:
                    raise ValueError(f'Expected an x64 Microsoft runtime: {path.name}')
                binary.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
                vc_exports[name] = {entry.name or entry.ordinal for entry in binary.DIRECTORY_ENTRY_EXPORT.symbols}
            vc_libraries[path.relative_to(app).as_posix()] = {
                'sha256': digest,
                'source': f'Build Python installation, {name}',
            }
    if not vc_libraries:
        raise ValueError('Expected the Microsoft runtime supplied with the bundled Python.')

    runtime_importers = {name: [] for name in vc_exports}
    directories = [
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT'],
    ]
    for path in sorted(app.rglob('*')):
        if path.suffix.lower() not in {'.exe', '.dll', '.pyd'} or not path.is_file():
            continue
        with pefile.PE(str(path), fast_load=True) as binary:
            if binary.FILE_HEADER.Machine != 0x8664:
                continue
            binary.parse_data_directories(directories=directories)
            imports = (
                *getattr(binary, 'DIRECTORY_ENTRY_IMPORT', ()),
                *getattr(binary, 'DIRECTORY_ENTRY_DELAY_IMPORT', ()),
            )
        for library in imports:
            name = library.dll.decode('ascii').lower()
            if VC_RUNTIME.match(name):
                symbols = {entry.name or entry.ordinal for entry in library.imports}
                missing = symbols - vc_exports.get(name, set())
                if missing:
                    raise ValueError(f'{path.name} needs unavailable exports from {name}: {missing}')
                runtime_importers[name].append(path.relative_to(app).as_posix())
    return {
        'system_ucrt': True,
        'omitted_system_libraries': system_libraries,
        'bundled_visual_cpp_libraries': vc_libraries,
        'verified_visual_cpp_importers': runtime_importers,
        'redistribution_terms': 'https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files',
    }


def main():
    app, cache = (Path(value).resolve() for value in sys.argv[1:3])
    notices = app / 'licenses'
    notices.mkdir()
    shutil.copy2(ROOT / 'LICENSE', notices / 'PyMoviePrint-LICENSE.txt')
    manifest = {
        'source_commit': subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD'], text=True).strip(),
        'python': sys.version,
        'build_packages': python_notices(notices),
        'ffmpeg': ffmpeg_runtime(app, cache, notices),
        'opencv': opencv_runtime(app, cache, notices),
        'numpy': numpy_runtime(app),
        'windows_runtime': windows_runtime(app),
        'distribution_status': 'Private candidate. Public distribution pending owner approval, source delivery, and Microsoft runtime terms.',
    }
    (app / 'dependency-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
