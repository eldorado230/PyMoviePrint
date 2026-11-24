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


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ffmpeg_runtime(app, cache, notices):
    pin = json.loads((ROOT / 'windows' / 'ffmpeg-runtime.json').read_bytes())
    archive = cache / pin['url'].rsplit('/', 1)[-1]
    if not archive.exists():
        partial = archive.with_suffix('.part')
        try:
            request = urllib.request.Request(pin['url'], headers={'User-Agent': 'PyMoviePrint-build'})
            with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            if sha256(partial) != pin['sha256']:
                raise ValueError('Downloaded FFmpeg archive does not match the pinned checksum.')
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    if sha256(archive) != pin['sha256']:
        raise ValueError(f'Cached FFmpeg archive does not match the pinned checksum: {archive}')

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
        'distribution_status': 'Internal prototype. Public redistribution review pending.',
    }
    (app / 'dependency-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
