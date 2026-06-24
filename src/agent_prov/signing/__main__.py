"""Command-line entry point: ``python -m agent_prov.signing <command>``.

Three subcommands:

* ``keygen``  -- generate an Ed25519 keypair as PEM files.
* ``sign``    -- sign a sealed bundle, writing a detached ``.sig`` envelope.
* ``verify``  -- verify a bundle against its ``.sig`` envelope.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from cryptography.hazmat.primitives import serialization

from agent_prov.signing import (
    BundleSignatureError,
    generate_keypair,
    load_private_key,
    load_public_key,
    sign_bundle,
    verify_signature,
)


def _cmd_keygen(args: argparse.Namespace) -> int:
    private_key, public_key = generate_keypair()
    args.out_private.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    print(f"wrote private key to {args.out_private}")
    if args.out_public is not None:
        args.out_public.write_bytes(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        print(f"wrote public key to {args.out_public}")
    return 0


def _cmd_sign(args: argparse.Namespace) -> int:
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    private_key = load_private_key(args.key.read_bytes())
    envelope = sign_bundle(bundle, private_key)
    out = args.out if args.out is not None else args.bundle.with_suffix(
        args.bundle.suffix + ".sig"
    )
    out.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    print(f"signed {args.bundle} -> {out}")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    sig_path = args.signature if args.signature is not None else args.bundle.with_suffix(
        args.bundle.suffix + ".sig"
    )
    envelope = json.loads(sig_path.read_text(encoding="utf-8"))
    public_key = load_public_key(args.key.read_bytes()) if args.key is not None else None

    result = verify_signature(bundle, envelope, public_key=public_key)
    if result.ok:
        scope = "with provided public key" if public_key is not None else "(key from envelope; authorship not bound)"
        print(f"OK: signature verified {scope}")
        return 0

    print(f"FAILED: {len(result.errors)} problem(s) found", file=sys.stderr)
    for err in result.errors:
        print(f"  - {err}", file=sys.stderr)
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent_prov.signing",
        description="Sign and verify detached signatures over a sealed Pipeline Bundle.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_keygen = sub.add_parser("keygen", help="generate an Ed25519 keypair (PEM)")
    p_keygen.add_argument("--out-private", type=pathlib.Path, required=True)
    p_keygen.add_argument("--out-public", type=pathlib.Path, default=None)
    p_keygen.set_defaults(func=_cmd_keygen)

    p_sign = sub.add_parser("sign", help="sign a bundle, writing a .sig envelope")
    p_sign.add_argument("bundle", type=pathlib.Path, help="path to bundle JSON")
    p_sign.add_argument("--key", type=pathlib.Path, required=True, help="private key PEM")
    p_sign.add_argument(
        "-o", "--out", type=pathlib.Path, default=None,
        help="signature output path (default: <bundle>.sig)",
    )
    p_sign.set_defaults(func=_cmd_sign)

    p_verify = sub.add_parser("verify", help="verify a bundle against its .sig")
    p_verify.add_argument("bundle", type=pathlib.Path, help="path to bundle JSON")
    p_verify.add_argument(
        "signature", type=pathlib.Path, nargs="?", default=None,
        help="path to signature JSON (default: <bundle>.sig)",
    )
    p_verify.add_argument(
        "--key", type=pathlib.Path, default=None,
        help="trusted public key PEM (default: use the key embedded in the envelope)",
    )
    p_verify.set_defaults(func=_cmd_verify)
    return parser


def _cli(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BundleSignatureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
