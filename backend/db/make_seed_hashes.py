"""Regenerate the argon2 password hashes used in db/seed.sql.

    python db/make_seed_hashes.py [password]      # default demo password: Passw0rd!

Every '$argon2...' literal in seed.sql is replaced in place with a fresh hash of the
given password, and the hash is printed too.
"""
import re
import sys
from pathlib import Path

from argon2 import PasswordHasher

password = sys.argv[1] if len(sys.argv) > 1 else "Passw0rd!"
hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)   # same params as app/security.py
seed = Path(__file__).resolve().parent / "seed.sql"
text = seed.read_text(encoding="utf-8")
count = 0


def swap(_match):
    global count
    count += 1
    return hasher.hash(password)


new_text = re.sub(r"\$argon2[^']+", swap, text)
seed.write_text(new_text, encoding="utf-8")
print(f"updated {count} hash(es) in {seed.name} for password {password!r}")
print(hasher.hash(password))
