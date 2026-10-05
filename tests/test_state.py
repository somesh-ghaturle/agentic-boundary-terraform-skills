"""State moves between the project and the gated copy without following symlinks."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

STATE = pathlib.Path(__file__).resolve().parents[1] / "skills/terraform-boundary/scripts/state.py"


def run(*args):
    return subprocess.run([sys.executable, str(STATE), *args], capture_output=True, text=True)


class State(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.env, self.run_dir = self.root / "env", self.root / "run"
        self.env.mkdir()
        self.run_dir.mkdir()
        self.secret = self.root / "secret"
        self.secret.write_text("not state")

    def test_round_trip(self):
        (self.env / "terraform.tfstate").write_text("v1")
        self.assertEqual(run("in", str(self.env), str(self.run_dir)).returncode, 0)
        (self.run_dir / "terraform.tfstate").write_text("v2")
        self.assertEqual(run("out", str(self.run_dir), str(self.env), os.path.realpath(self.env)).returncode, 0)
        self.assertEqual((self.env / "terraform.tfstate").read_text(), "v2")

    def test_copy_in_refuses_a_symlink(self):
        (self.env / "terraform.tfstate").symlink_to(self.secret)
        self.assertNotEqual(run("in", str(self.env), str(self.run_dir)).returncode, 0)
        self.assertFalse((self.run_dir / "terraform.tfstate").exists())

    def test_copy_out_replaces_a_symlink_instead_of_writing_through_it(self):
        (self.env / "terraform.tfstate").symlink_to(self.secret)
        (self.run_dir / "terraform.tfstate").write_text("state")
        self.assertEqual(run("out", str(self.run_dir), str(self.env), os.path.realpath(self.env)).returncode, 0)
        self.assertEqual(self.secret.read_text(), "not state")
        self.assertFalse((self.env / "terraform.tfstate").is_symlink())

    def test_copy_out_refuses_a_moved_env_dir(self):
        (self.run_dir / "terraform.tfstate").write_text("state")
        physical = os.path.realpath(self.env)
        moved = self.root / "elsewhere"
        self.env.rename(moved)
        self.env.symlink_to(moved)
        self.assertNotEqual(run("out", str(self.run_dir), str(self.env), physical).returncode, 0)
        self.assertFalse((moved / "terraform.tfstate").exists())


if __name__ == "__main__":
    unittest.main()
