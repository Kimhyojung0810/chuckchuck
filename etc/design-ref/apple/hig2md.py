"""Apple HIG 페이지 JSON(developer.apple.com/tutorials/data/design/human-interface-guidelines/<page>.json) → 읽을 마크다운."""
import json, sys
from pathlib import Path

def inl(xs, refs):
    out = []
    for x in xs or []:
        t = x.get('type')
        if t == 'text': out.append(x['text'])
        elif t in ('emphasis', 'strong'): out.append(('**' if t == 'strong' else '*') + inl(x.get('inlineContent'), refs) + ('**' if t == 'strong' else '*'))
        elif t == 'codeVoice': out.append('`' + x.get('code', '') + '`')
        elif t == 'reference': out.append((refs.get(x.get('identifier'), {}) or {}).get('title', ''))
        elif t == 'image': out.append('[그림]')
        else: out.append(inl(x.get('inlineContent'), refs))
    return ''.join(out)

def block(b, refs, lines):
    t = b.get('type')
    if t == 'heading': lines.append('\n' + '#' * min(6, b.get('level', 2) + 1) + ' ' + b.get('text', ''))
    elif t == 'paragraph': lines.append(inl(b.get('inlineContent'), refs))
    elif t in ('unorderedList', 'orderedList'):
        for k, it in enumerate(b.get('items', [])):
            sub = []
            for c in it.get('content', []): block(c, refs, sub)
            lines.append(('- ' if t == 'unorderedList' else f'{k + 1}. ') + ' '.join(s.strip() for s in sub if s.strip()))
    elif t == 'table':
        for k, row in enumerate(b.get('rows', [])):
            cells = []
            for cell in row:
                sub = []
                for c in cell: block(c, refs, sub)
                cells.append(' '.join(s.strip() for s in sub if s.strip()))
            lines.append('| ' + ' | '.join(cells) + ' |')
            if k == 0: lines.append('|' + '---|' * len(cells))
    elif t == 'aside':
        sub = []
        for c in b.get('content', []): block(c, refs, sub)
        lines.append('> ' + ' '.join(s.strip() for s in sub if s.strip()))
    elif t == 'row':
        for col in b.get('columns', []):
            for c in col.get('content', []): block(c, refs, lines)
    elif 'content' in b:
        for c in b['content']: block(c, refs, lines)

for p in sys.argv[1:]:
    d = json.loads(Path(p).read_text())
    refs = d.get('references', {})
    lines = [f"# {d.get('metadata', {}).get('title', Path(p).stem)}", f"출처: https://developer.apple.com/design/human-interface-guidelines/{Path(p).stem}", '']
    for a in d.get('abstract', []): lines.append(inl([a], refs))
    for sec in d.get('primaryContentSections', []):
        for c in sec.get('content', []): block(c, refs, lines)
    Path(p).with_suffix('.md').write_text('\n'.join(lines) + '\n')
    print(Path(p).with_suffix('.md').name, len(lines))
