#!/usr/bin/env python3
"""Release-file checks. Reports filenames and rule names, never matched secrets."""
import argparse
import re
from pathlib import Path
from build_deb import source_files

RULES = {
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'github-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'aws-access-key': re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
    'url-credentials': re.compile(r'https?://[^\s/\'"{}:]+:[^\s/\'"{}@]+@'),
}

def scan(root, forbidden=()):
    findings=[]
    for path in source_files(root):
        text=path.read_bytes().decode('utf-8',errors='replace')
        for rule,pattern in RULES.items():
            if pattern.search(text):findings.append((str(path.relative_to(root)),rule))
        if any(value and value.casefold() in text.casefold() for value in forbidden):
            findings.append((str(path.relative_to(root)),'host-specific-value'))
    return findings

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--forbidden-file',type=Path,help='Private local list of values to reject; never commit it.')
    args=parser.parse_args()
    forbidden=args.forbidden_file.read_text().splitlines() if args.forbidden_file else ()
    findings=scan(args.source,forbidden)
    for path,rule in findings:print(path+': '+rule)
    print(str(len(findings))+' findings; heuristic check, not a guarantee of absence.')
    return bool(findings)
if __name__=='__main__':raise SystemExit(main())
