from pathlib import Path

path = Path('.github/apply_preview_export_parity.py')
text = path.read_text(encoding='utf-8')
old = '''def replace_once(path, old, new, label):
    path = ROOT / path
    with open(path, 'r', encoding='utf-8', newline='') as handle:
        text = handle.read()
    pattern = r'\\r?\\n'.join(re.escape(line) for line in textwrap.dedent(old).strip('\\n').split('\\n'))
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise RuntimeError(f"{label}: expected exactly one match in {path}, found {len(matches)}")
    match = matches[0]
    matched = match.group(0)
    eol = '\\r\\n' if '\\r\\n' in matched else '\\n'
    replacement = textwrap.dedent(new).strip('\\n').replace('\\n', eol)
    text = text[:match.start()] + replacement + text[match.end():]
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text)
'''
new = '''def _indent_candidate(block, extra):
    lines = textwrap.dedent(block).strip('\\n').split('\\n')
    prefix = ' ' * extra
    return '\\n'.join(prefix + line if line else '' for line in lines)


def replace_once(path, old, new, label):
    path = ROOT / path
    with open(path, 'r', encoding='utf-8', newline='') as handle:
        text = handle.read()

    selected = None
    for extra in (0, 4, 8, 12, 16, 20):
        candidate = _indent_candidate(old, extra)
        pattern = r'\\r?\\n'.join(re.escape(line) for line in candidate.split('\\n'))
        matches = list(re.finditer(pattern, text))
        if len(matches) == 1:
            selected = (matches[0], extra)
            break
    if selected is None:
        raise RuntimeError(f"{label}: expected exactly one indented match in {path}")

    match, extra = selected
    matched = match.group(0)
    eol = '\\r\\n' if '\\r\\n' in matched else '\\n'
    replacement = _indent_candidate(new, extra).replace('\\n', eol)
    text = text[:match.start()] + replacement + text[match.end():]
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        handle.write(text)
'''
if old not in text:
    raise SystemExit('Original helper not found')
path.write_text(text.replace(old, new), encoding='utf-8')
