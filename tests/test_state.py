"""State moves between the project and the gated copy without following symlinks, and only into
the exact directory apply started with."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

STATE = pathlib.Path(__file__).resolve().parents[1] / "skills/terraform-boundary/scripts/state.py"


def run(*args):
    return subprocess.run([sys.executable, str(STATE), *map(str, args)], capture_output=True, text=True)


class State(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.env, self.run_dir = self.root / "env", self.root / "run"
        self.env.mkdir()
        self.run_dir.mkdir()
        self.secret = self.root / "secret"
        self.secret.write_text("not state")
        self.envid = run("id", self.env).stdout.strip()

    def test_round_trip(self):
        (self.env / "terraform.tfstate").write_text("v1")
        self.assertEqual(run("in", self.env, self.envid, self.run_dir).returncode, 0)
        self.assertEqual((self.run_dir / "terraform.tfstate").read_text(), "v1")
        (self.run_dir / "terraform.tfstate").write_text("v2")
        self.assertEqual(run("out", self.run_dir, self.env, self.envid).returncode, 0)
        self.assertEqual((self.env / "terraform.tfstate").read_text(), "v2")

    def test_id_refuses_a_symlinked_env_dir(self):
        link = self.root / "link"
        link.symlink_to(self.env)
        self.assertNotEqual(run("id", link).returncode, 0)

    def test_copy_in_refuses_a_symlinked_state_file(self):
        (self.env / "terraform.tfstate").symlink_to(self.secret)
        self.assertNotEqual(run("in", self.env, self.envid, self.run_dir).returncode, 0)
        self.assertFalse((self.run_dir / "terraform.tfstate").exists())

    def test_copy_out_replaces_a_symlink_instead_of_writing_through_it(self):
        (self.env / "terraform.tfstate").symlink_to(self.secret)
        (self.run_dir / "terraform.tfstate").write_text("state")
        self.assertEqual(run("out", self.run_dir, self.env, self.envid).returncode, 0)
        self.assertEqual(self.secret.read_text(), "not state")
        self.assertFalse((self.env / "terraform.tfstate").is_symlink())

    def test_copy_out_refuses_a_symlink_to_a_different_dir(self):
        (self.run_dir / "terraform.tfstate").write_text("state")
        decoy = self.root / "decoy"
        decoy.mkdir()
        self.env.rename(self.root / "original")
        self.env.symlink_to(decoy)
        self.assertNotEqual(run("out", self.run_dir, self.env, self.envid).returncode, 0)
        self.assertFalse((decoy / "terraform.tfstate").exists())

    def test_copy_out_follows_the_original_dir_by_identity_not_by_path(self):
        # The same directory, moved and reached through a symlink, is still where state belongs.
        (self.run_dir / "terraform.tfstate").write_text("state")
        moved = self.root / "moved"
        self.env.rename(moved)
        self.env.symlink_to(moved)
        self.assertEqual(run("out", self.run_dir, self.env, self.envid).returncode, 0)
        self.assertEqual((moved / "terraform.tfstate").read_text(), "state")

    def test_copy_out_refuses_an_env_dir_swapped_for_another_real_dir(self):
        (self.run_dir / "terraform.tfstate").write_text("state")
        self.env.rename(self.root / "original")
        self.env.mkdir()
        self.assertNotEqual(run("out", self.run_dir, self.env, self.envid).returncode, 0)
        self.assertFalse((self.env / "terraform.tfstate").exists())


if __name__ == "__main__":
    unittest.main()
