#!/usr/bin/env python3
"""Move Terraform state between the project and the gated copy without following symlinks.

    state.py id  <envdir>                       print the directory's identity
    state.py in  <envdir> <identity> <run>
    state.py out <run> <envdir> <identity>

The project is writable by the agent, so any path in it, the env directory or one of its parents
included, could be swapped for a symlink or another directory between steps. So apply records
the env directory's identity (device and inode) once, at the start. Every later step opens the
directory, refuses if its identity changed, and does all file work relative to that open handle:
reads with O_NOFOLLOW, writes to a new file and renames it into place. Nothing re-resolves the
path after the identity check.
"""
import os
import stat
import sys

FILES = ("terraform.tfstate", "terraform.tfstate.backup")


def identity(st):
    return f"{st.st_dev}:{st.st_ino}"


def open_dir(envdir, expected):
    dfd = os.open(envdir, os.O_RDONLY | os.O_DIRECTORY)
    if identity(os.fstat(dfd)) != expected:
        os.close(dfd)
        sys.exit(f"{envdir} is no longer the directory apply started with; not touching state")
    return dfd


def copy_in(envdir, expected, run):
    dfd = open_dir(envdir, expected)
    for name in FILES:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
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


def copy_out(run, envdir, expected):
    dfd = open_dir(envdir, expected)
    for name in FILES:
        src = os.path.join(run, name)
        if not os.path.isfile(src):
            continue
        with open(src, "rb") as fh:
            data = fh.read()
        tmp = f".{name}.{os.getpid()}.boundary"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        with os.fdopen(fd, "wb") as dst:
            dst.write(data)
            dst.flush()
            os.fsync(dst.fileno())
        os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    os.fsync(dfd)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["id"] and len(args) == 2:
        st = os.lstat(args[1])
        if not stat.S_ISDIR(st.st_mode):
            sys.exit(f"{args[1]} is not a directory, or is a symlink")
        print(identity(st))
    elif args[:1] == ["in"] and len(args) == 4:
        copy_in(*args[1:])
    elif args[:1] == ["out"] and len(args) == 4:
        copy_out(*args[1:])
    else:
        sys.exit(__doc__)
