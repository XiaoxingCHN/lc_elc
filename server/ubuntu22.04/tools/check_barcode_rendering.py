#!/usr/bin/env python3
"""Check the actual bitmap backend required by Odoo QWeb barcode reports.

Run with the Odoo virtual environment's Python. No database or stock writes.
A ReportLab import alone is insufficient: v4 bitmap renderers are optional.
"""
import io
import json
import sys
from importlib import metadata


def main():
    from PIL import Image
    from reportlab import rl_config
    from reportlab.graphics.barcode import createBarcodeDrawing

    results = []
    for kind, value, width, height in (
        ("Code128", "LABL:RENDER-CHECK", 500, 120),
        ("QR", "LABB:RENDER-CHECK", 256, 256),
    ):
        image = createBarcodeDrawing(kind, value=value, width=width, height=height).asString("png")
        if not image.startswith(bytes.fromhex("89504e470d0a1a0a")):
            raise RuntimeError("Barcode output is not PNG")
        with Image.open(io.BytesIO(image)) as bitmap:
            bitmap.load()
            if bitmap.size != (width, height):
                raise RuntimeError("Unexpected barcode dimensions")
            results.append({"kind": kind, "width": bitmap.width, "height": bitmap.height, "bytes": len(image)})
    print(json.dumps({"reportlab": metadata.version("reportlab"), "configured_backend": rl_config.renderPMBackend, "barcodes": results}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Odoo barcode rendering check failed: " + str(exc), file=sys.stderr)
        print("ReportLab 4 needs a bitmap backend. Keep the installed ReportLab version; install its renderpm extra or a compatible rl-renderPM wheel into the Odoo venv, then rerun this check.", file=sys.stderr)
        raise SystemExit(1)
