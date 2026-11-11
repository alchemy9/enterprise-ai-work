"""Non-destructive SQLite online backup; output must be a new file."""
import argparse
import sqlite3
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent.parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default=str(root/'var'/'eaw.sqlite3'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    source=Path(args.db).resolve()
    output=Path(args.output).resolve()
    if not source.is_file() or output.exists() or source==output:
        parser.error('source must exist and output must be a new, distinct file')
    output.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(output) as dst:
        src.backup(dst)
        check=dst.execute('PRAGMA integrity_check').fetchone()[0]
        if check!='ok':
            raise RuntimeError('backup integrity check failed')
    print(f'Backup verified: {output}')


if __name__=='__main__':
    main()
