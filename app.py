import io
import os
import sys
import base64
import socket
import threading
import webbrowser
from flask import Flask, render_template, request, send_file, jsonify
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import (
    SquareModuleDrawer,
    RoundedModuleDrawer,
    CircleModuleDrawer,
    GappedSquareModuleDrawer
)
from PIL import Image, ImageDraw

# Determine template folder for both normal Python and PyInstaller onefile EXE
if getattr(sys, "frozen", False):
    template_folder = os.path.join(sys._MEIPASS, "templates")
else:
    template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

app = Flask(__name__, template_folder=template_folder)

EC_MAP = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}

DRAWER_MAP = {
    "square": SquareModuleDrawer(),
    "rounded": RoundedModuleDrawer(),
    "circle": CircleModuleDrawer(),
    "dots": CircleModuleDrawer(),
    "gapped": GappedSquareModuleDrawer(),
}

def parse_color(hex_str, default=(0, 0, 0, 255)):
    if not hex_str:
        return default
    hex_str = hex_str.strip().lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join([c * 2 for c in hex_str])
    if len(hex_str) == 6:
        try:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            return (r, g, b, 255)
        except ValueError:
            return default
    if len(hex_str) == 8:
        try:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            a = int(hex_str[6:8], 16)
            return (r, g, b, a)
        except ValueError:
            return default
    return default

def make_qr_image(
    data,
    box_size=10,
    border=2,
    ec_level="M",
    color_dark="#000000",
    color_light="#ffffff",
    dot_style="square",
    logo_base64=None
):
    ec = EC_MAP.get(str(ec_level).upper(), qrcode.constants.ERROR_CORRECT_M)
    if logo_base64:
        ec = qrcode.constants.ERROR_CORRECT_H

    qr = qrcode.QRCode(
        version=None,
        error_correction=ec,
        box_size=max(2, min(40, int(box_size))),
        border=max(0, min(10, int(border))),
    )
    qr.add_data(data)
    qr.make(fit=True)

    drawer = DRAWER_MAP.get(dot_style, SquareModuleDrawer())

    is_transparent = (str(color_light).lower() in ["transparent", "none", "rgba(0,0,0,0)"])
    dark_rgba = parse_color(color_dark, (0, 0, 0, 255))
    light_rgba = (255, 255, 255, 0) if is_transparent else parse_color(color_light, (255, 255, 255, 255))

    # Render base QR image
    if dot_style == "square" and not is_transparent:
        img = qr.make_image(
            fill_color=dark_rgba[:3],
            back_color=light_rgba[:3]
        ).convert("RGBA")
    else:
        # Styled rendering
        base_img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=drawer
        ).convert("RGBA")
        
        # Colorize modules
        data_pix = base_img.getdata()
        new_pix = []
        for p in data_pix:
            # Check darkness
            if p[0] < 128:
                new_pix.append(dark_rgba)
            else:
                new_pix.append(light_rgba)
        base_img.putdata(new_pix)
        img = base_img

    # Embed logo if provided
    if logo_base64:
        try:
            if "," in logo_base64:
                logo_base64 = logo_base64.split(",", 1)[1]
            logo_bytes = base64.b64decode(logo_base64)
            logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")

            qr_w, qr_h = img.size
            logo_max_size = int(qr_w * 0.24)
            logo_img.thumbnail((logo_max_size, logo_max_size), Image.Resampling.LANCZOS)
            lw, lh = logo_img.size

            # Create circular/rounded white backing badge
            pad = 8
            badge_w = lw + pad * 2
            badge_h = lh + pad * 2
            badge = Image.new("RGBA", (badge_w, badge_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(badge)
            draw.rounded_rectangle([0, 0, badge_w, badge_h], radius=12, fill=(255, 255, 255, 255))

            bx = (qr_w - badge_w) // 2
            by = (qr_h - badge_h) // 2
            img.paste(badge, (bx, by), badge)

            lx = (qr_w - lw) // 2
            ly = (qr_h - lh) // 2
            img.paste(logo_img, (lx, ly), logo_img)
        except Exception:
            pass

    return img

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(silent=True) or {}
    data = str(payload.get("data", "")).strip()
    if not data:
        return jsonify({"error": "Enter text, a URL, phone number, or other content first."}), 400

    box_size = payload.get("box_size", 10)
    border = payload.get("border", 2)
    ec_level = payload.get("error_correction", "M")
    color_dark = payload.get("color_dark", "#000000")
    color_light = payload.get("color_light", "#ffffff")
    dot_style = payload.get("dot_style", "square")
    logo_base64 = payload.get("logo_base64", None)

    try:
        image = make_qr_image(
            data=data,
            box_size=box_size,
            border=border,
            ec_level=ec_level,
            color_dark=color_dark,
            color_light=color_light,
            dot_style=dot_style,
            logo_base64=logo_base64
        )
        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return send_file(
            output,
            mimetype="image/png",
            as_attachment=False,
            download_name="qr-code.png",
            max_age=0,
        )
    except Exception as e:
        return jsonify({"error": f"Failed to generate QR code: {str(e)}"}), 500

def find_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def open_browser(port):
    webbrowser.open(f"http://127.0.0.1:{port}/")

if __name__ == "__main__":
    port = find_port()
    threading.Timer(1.0, open_browser, args=(port,)).start()
    print(f"SPVM3 Local QR Code Studio running at http://127.0.0.1:{port}/")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
