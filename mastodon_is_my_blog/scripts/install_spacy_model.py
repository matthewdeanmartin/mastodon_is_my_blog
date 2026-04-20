"""Download the en_core_web_sm spaCy model. Run once after install."""

import subprocess
import sys

if __name__ == "__main__":
    subprocess.run(
        [sys.executable, "-m", "spacy", "download", "en_core_web_sm"],
        check=True,
    )
    print("en_core_web_sm installed.")
