#!/usr/bin/env python3

import argparse

parser = argparse.ArgumentParser()
parser.add_argument("sharepath")
parser.add_argument("pkgname")
parser.add_argument("filename")

args = parser.parse_args()

print(f"""#!/usr/bin/env python3

import os
import sys
sys.path.insert(0, "{args.sharepath}")
from {args.pkgname} import {args.filename}

{args.filename}.runcli()""")
