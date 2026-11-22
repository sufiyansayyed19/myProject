"""Generate a local development RS256 RSA keypair in ./keys/ (gitignored)."""

import argparse
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_keys(output_dir: Path, force: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    private_path = output_dir / "jwt_private.pem"
    public_path = output_dir / "jwt_public.pem"

    if (private_path.exists() or public_path.exists()) and not force:
        print(f"Keys already exist in {output_dir}. Use --force to overwrite.")
        return

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    print(f"Generated RS256 dev keys:\n  Private: {private_path}\n  Public:  {public_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate local RS256 dev keys.")
    parser.add_argument("--out", default="keys", help="Output directory (default: keys)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing keys")
    args = parser.parse_args()
    generate_keys(Path(args.out), force=args.force)
