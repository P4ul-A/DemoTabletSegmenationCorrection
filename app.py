"""Serve a single-image segmentation correction session on the local network."""

import argparse
import colorsys
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
import socket
import subprocess
import webbrowser

import cv2
import numpy as np
from PIL import Image, ImageOps

from segmenter import segment


STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_IMAGE = Path(__file__).with_name("demo") / "toyota.jpeg"
MAX_WORKING_DIMENSION = 1600


def local_ip() -> str:
    """Find the LAN address used for the iPad connection.

    Args:
        None.

    Returns:
        The host's preferred IPv4 address, or a loopback address if none is
        available. Use ``--lan-ip`` when the automatic choice is unsuitable.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(("192.0.2.1", 80))
            return connection.getsockname()[0]
    except OSError:
        # Some restricted environments block the route lookup above. On Macs,
        # try the usual network interfaces before asking for --lan-ip.
        for interface in ("en0", "en1", "en2", "en3"):
            try:
                result = subprocess.run(
                    ["ifconfig", interface], capture_output=True, text=True, check=False
                )
            except FileNotFoundError:
                break
            match = re.search(r"\binet (\d{1,3}(?:\.\d{1,3}){3})\b", result.stdout)
            if match:
                return match.group(1)
        return "127.0.0.1"


def png_bytes(image: Image.Image) -> bytes:
    """Encode a Pillow image as PNG bytes.

    Args:
        image: Image to encode.

    Returns:
        The encoded PNG bytes.
    """
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def class_palette() -> list[tuple[int, int, int]]:
    """Build the shared display palette for all possible uint8 class IDs.

    Args:
        None.

    Returns:
        A list of 256 RGB colors, starting with black for background.
    """
    colors = [(0, 0, 0)]
    for class_id in range(1, 256):
        hue = ((class_id * 137.508) % 360) / 360
        rgb = colorsys.hsv_to_rgb(hue, 0.78, 0.95)
        colors.append(tuple(round(component * 255) for component in rgb))
    return colors


def preview_png(
    image: Image.Image, mask: np.ndarray, palette: list[tuple[int, int, int]]
) -> bytes:
    """Render the current segmentation as a translucent image overlay.

    Args:
        image: RGB working image shown in the editor.
        mask: Working-size array of class IDs.
        palette: RGB color for each possible class ID.

    Returns:
        PNG bytes for the host browser preview.
    """
    colors = np.asarray(palette, dtype=np.uint8)[mask]
    alpha = np.where(mask == 0, 0, 145).astype(np.uint8)
    overlay = Image.fromarray(np.dstack((colors, alpha)), mode="RGBA")
    return png_bytes(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"))


def qr_png(url: str) -> bytes:
    """Create a scannable QR code for a local editor URL.

    Args:
        url: URL to encode.

    Returns:
        PNG bytes containing a white-bordered QR code.
    """
    matrix = cv2.QRCodeEncoder_create().encode(url)
    qr = Image.fromarray(matrix).convert("L")
    bordered = Image.new("L", (qr.width + 8, qr.height + 8), 255)
    bordered.paste(qr, (4, 4))
    bordered = bordered.resize((bordered.width * 8, bordered.height * 8), Image.Resampling.NEAREST)
    return png_bytes(bordered)


def load_image(path: Path) -> tuple[Image.Image, tuple[int, int]]:
    """Open an image and make a browser-sized copy with correct orientation.

    Args:
        path: Image file to open.

    Returns:
        RGB working image and the oriented source image size.
    """
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    source_size = image.size
    image.thumbnail((MAX_WORKING_DIMENSION, MAX_WORKING_DIMENSION), Image.Resampling.LANCZOS)
    return image, source_size


def make_handler(
    image: Image.Image,
    source_size: tuple[int, int],
    initial_mask: np.ndarray,
    classes: list[str],
    output_path: Path,
    editor_url: str,
) -> type[BaseHTTPRequestHandler]:
    """Build the HTTP handler for one image correction session.

    Args:
        image: Browser-sized RGB image.
        source_size: Oriented source image width and height.
        initial_mask: Browser-sized uint8 class ID mask.
        classes: Class names in ID order, with background at index zero.
        output_path: Destination for the corrected class ID PNG.
        editor_url: LAN URL encoded in the QR code.

    Returns:
        A request handler class for Python's HTTPServer.
    """
    image_bytes = png_bytes(image)
    code_bytes = qr_png(editor_url)
    palette = class_palette()
    preview_bytes = preview_png(image, initial_mask, palette)
    version = 0
    session_bytes = json.dumps(
        {
            "width": image.width,
            "height": image.height,
            "classes": classes,
            "palette": palette[:len(classes)],
            "editor_url": editor_url,
        }
    ).encode("utf-8")
    mask = initial_mask.copy()

    class Handler(BaseHTTPRequestHandler):
        """Serve the connection page, editor assets, and one mask save endpoint."""

        def send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
            """Send a complete HTTP response.

            Args:
                data: Response body.
                content_type: HTTP Content-Type value.
                status: HTTP status code.

            Returns:
                None.
            """
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            """Serve the connection page, editor, and current image data.

            Args:
                None.

            Returns:
                None.
            """
            path = self.path.split("?", 1)[0]
            if path == "/":
                self.send_bytes((STATIC_DIR / "connect.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/edit":
                self.send_bytes((STATIC_DIR / "editor.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/editor.js":
                self.send_bytes((STATIC_DIR / "editor.js").read_bytes(), "text/javascript; charset=utf-8")
            elif path == "/qr.png":
                self.send_bytes(code_bytes, "image/png")
            elif path == "/api/session":
                self.send_bytes(session_bytes, "application/json")
            elif path == "/api/image":
                self.send_bytes(image_bytes, "image/png")
            elif path == "/api/preview.png":
                self.send_bytes(preview_bytes, "image/png")
            elif path == "/api/version":
                self.send_bytes(str(version).encode("ascii"), "text/plain; charset=utf-8")
            elif path == "/api/mask":
                self.send_bytes(mask.tobytes(), "application/octet-stream")
            else:
                self.send_bytes(b"Not found", "text/plain; charset=utf-8", 404)

        def do_POST(self) -> None:
            """Validate and save a complete class ID mask from the editor.

            Args:
                None.

            Returns:
                None.
            """
            nonlocal mask, preview_bytes, version
            if self.path != "/api/mask":
                self.send_bytes(b"Not found", "text/plain; charset=utf-8", 404)
                return
            expected = image.width * image.height
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if length != expected:
                self.send_bytes(b"Wrong mask size", "text/plain; charset=utf-8", 400)
                return
            data = self.rfile.read(length)
            if len(data) != expected:
                self.send_bytes(b"Incomplete mask", "text/plain; charset=utf-8", 400)
                return
            updated = np.frombuffer(data, dtype=np.uint8).reshape((image.height, image.width))
            if int(updated.max()) >= len(classes):
                self.send_bytes(b"Unknown class ID", "text/plain; charset=utf-8", 400)
                return
            try:
                updated_preview = preview_png(image, updated, palette)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # Palette PNGs display in color but retain each class ID as
                # the stored pixel value for downstream segmentation code.
                saved = Image.fromarray(updated, mode="P")
                saved.putpalette([component for color in palette for component in color])
                if saved.size != source_size:
                    saved = saved.resize(source_size, Image.Resampling.NEAREST)
                saved.save(output_path, format="PNG")
            except OSError as error:
                self.send_bytes(str(error).encode("utf-8"), "text/plain; charset=utf-8", 500)
                return
            mask = updated.copy()
            preview_bytes = updated_preview
            version += 1
            self.send_bytes(b"Saved", "text/plain; charset=utf-8")

    return Handler


def main() -> None:
    """Run inference, show the connection QR code, and serve the editor.

    Args:
        None. Command-line arguments provide the image and server settings.

    Returns:
        None.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "image", nargs="?", type=Path, default=DEFAULT_IMAGE,
        help="image to segment and correct (default: demo/toyota.jpeg)",
    )
    parser.add_argument("--output", type=Path, help="corrected class ID PNG path")
    parser.add_argument("--port", type=int, default=8765, help="local server port (default: 8765)")
    parser.add_argument("--lan-ip", help="LAN IPv4 address shown in the QR code")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    output_path = args.output or args.image.with_name(f"{args.image.stem}_corrected_mask.png")
    image, source_size = load_image(args.image)
    print("Running segmentation (model weights download on first use)...", flush=True)
    mask, classes = segment(image)
    if mask.shape != (image.height, image.width) or mask.dtype != np.uint8:
        raise ValueError("segment() must return a height-by-width uint8 mask")
    if not classes or len(classes) > 256 or int(mask.max()) >= len(classes):
        raise ValueError("segment() must return 1-256 class names matching the mask IDs")

    ip = args.lan_ip or local_ip()
    editor_url = f"http://{ip}:{args.port}/edit"
    handler = make_handler(image, source_size, mask, classes, output_path, editor_url)
    with HTTPServer(("0.0.0.0", args.port), handler) as server:
        print(f"Scan the QR code at http://127.0.0.1:{args.port}/", flush=True)
        print(f"iPad URL: {editor_url}", flush=True)
        print(f"Saving corrected mask to: {output_path}", flush=True)
        if ip.startswith("127."):
            print("No LAN address found. Restart with --lan-ip YOUR_LAN_IP.", flush=True)
        webbrowser.open(f"http://127.0.0.1:{args.port}/")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


if __name__ == "__main__":
    main()
