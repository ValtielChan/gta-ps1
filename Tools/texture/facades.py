"""Convert the facade sources family by family so every bay of a material matches its reference texture
(same wall color / contrast): a building only mixes bays of one family (see kit.STYLES).

  python -I Tools/texture/facades.py <raw dir with raw_<Name>.b64.txt>

The reference of each family is converted first without matching; the others get ps1ify --match on it.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEX = os.path.normpath(os.path.join(HERE, '..', '..', 'Assets', 'GTA', 'Textures'))

# family reference -> [(name, extra ps1ify args)]; crops drop what the generator added around the bay
FAMILIES = {
    'BrickBay':    [('Brick', []), ('BrickGround', []), ('BrickEntry', []), ('BrickService', [])],
    'BrickBayB':   [('BrickB', []), ('BrickBService', [])],
    'AptBay':      [('Stucco', []), ('StuccoBay', []), ('SpanishBay', ['--crop', '0', '0.06', '1', '1']),
                    ('AptEntry', ['--crop', '0.035', '0', '0.965', '1']), ('AptGround', []),
                    ('StuccoService', ['--crop', '0', '0', '1', '0.98'])],
    'OfficeGround': [('OfficeLobby', ['--crop', '0', '0', '1', '0.94']), ('GraniteService', []), ('GraniteGarage', [])],
    'DecoBay':     [('DecoEntry', []), ('DecoWall', [])],
}
REF_ARGS = {'OfficeGround': ['--crop', '0', '0', '1', '0.92']}


def ps1ify(raw_dir, name, args):
    src = os.path.join(raw_dir, 'raw_%s.png' % name)   # textures made before the raw was kept: their first PS1 version
    if not os.path.exists(src):
        src = os.path.join(raw_dir, 'raw_%s.b64.txt' % name)
    subprocess.run([sys.executable, '-I', os.path.join(HERE, 'ps1ify.py'), src,
                    os.path.join(TEX, 'T_%s.png' % name)] + args, check=True)


if __name__ == '__main__':
    raw = sys.argv[1]
    for ref, members in FAMILIES.items():
        ps1ify(raw, ref, REF_ARGS.get(ref, []))
        for name, args in members:
            ps1ify(raw, name, args + ['--match', os.path.join(TEX, 'T_%s.png' % ref)])
            print(ref, '->', name)
