import unittest

from jobhunt import filelock


class FileLock(unittest.TestCase):
    def test_acquire_then_release(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.lock"
            fh = open(path, "w")
            try:
                filelock.acquire(fh)  # should not raise
                filelock.release(fh)
                filelock.acquire(fh)  # re-acquire after release
                filelock.release(fh)
            finally:
                fh.close()


if __name__ == "__main__":
    unittest.main()
