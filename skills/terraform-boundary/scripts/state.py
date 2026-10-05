#!/usr/bin/env python3
"""Move Terraform state between the project and the gated copy without following symlinks.

    state.py in  <envdir> <run>
    state.py out <run> <envdir> <envdir-physical-path>

The project is writable by the agent, so a state file could be swapped for a symlink between
checks. Reading opens with O_NOFOLLOW and refuses anything but a regular file. Writing goes to a
new temporary file and is renamed into place; a rename replaces a symlink rather than writing
through it. The env directory's physical path is checked again before writing back.
"""
import os
import stat
import sys

FILES = ("terraform.tfstate", "terraform.tfstate.backup")


def copy_in(envdir, run):
    for name in FILES:
        try:
            fd = os.open(os.path.join(envdir, name), os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        except OSError as err:
            sys.exit(f"refusing {name}: {err.strerror} (is it a symlink?)")
        with os.fdopen(fd, "rb") as src:
            if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
                sys.exit(f"refusing {name}: not a regular file")
            data = src.read()
        with open(os.path.join(run, name), "wb") as dst:
            dst.write(data)


def copy_out(run, envdir, physical):
    if os.path.islink(envdir) or os.path.realpath(envdir) != physical:
        sys.exit(f"{envdir} moved or became a symlink; not writing state into it")
    for name in FILES:
        src = os.path.join(run, name)
        if not os.path.isfile(src):
            continue
        with open(src, "rb") as fh:
            data = fh.read()
        tmp = os.path.join(envdir, f".{name}.{os.getpid()}.boundary")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as dst:
            dst.write(data)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, os.path.join(envdir, name))


if __name__ == "__main__":
    if sys.argv[1:2] == ["in"] and len(sys.argv) == 4:
        copy_in(*sys.argv[2:])
    elif sys.argv[1:2] == ["out"] and len(sys.argv) == 5:
        copy_out(*sys.argv[2:])
    else:
        sys.exit(__doc__)
