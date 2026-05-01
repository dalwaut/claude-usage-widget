#!/usr/bin/env python3
"""Claude Usage Desktop Widget
Displays your Claude subscription usage (session + weekly limits) as a
desktop widget on Linux. Reads OAuth credentials from Claude Code or
lets you paste your own token.

Requires: python3, python3-gi, python3-gi-cairo
Install:  sudo apt install python3-gi python3-gi-cairo

Built by Boutabyte — https://boutabyte.com
"""

import json
import math
import signal
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib  # noqa: E402

# ── Config ────────────────────────────────────────────────
APP_NAME = "Claude Usage Widget"
APP_VERSION = "1.0.0"
CONFIG_DIR = Path.home() / ".config" / "claude-usage-widget"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
CLAUDE_CODE_CREDS = Path.home() / ".claude" / ".credentials.json"

ANTHROPIC_USAGE_API = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_BETA_HEADER = "oauth-2025-04-20"
POLL_SECONDS = 30
WIDGET_W = 280
TITLE_H = 36
COG_SIZE = 20

# Claude palette
C = {
    "bg":         (0.110, 0.090, 0.078),
    "terracotta": (0.851, 0.467, 0.341),
    "cream":      (0.910, 0.835, 0.769),
    "label":      (0.478, 0.396, 0.333),
    "dim":        (0.290, 0.247, 0.208),
    "bar_empty":  (0.239, 0.208, 0.161),
    "amber":      (0.910, 0.659, 0.298),
    "red":        (1.000, 0.333, 0.271),
    "green":      (0.400, 0.750, 0.400),
}


# ── Settings / Credentials ────────────────────────────────

def load_settings():
    defaults = {"opacity": 0.90, "x": -1, "y": -1}
    if SETTINGS_FILE.exists():
        try:
            defaults.update(json.loads(SETTINGS_FILE.read_text()))
        except Exception:
            pass
    return defaults


def save_settings(settings):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings))


def get_oauth_token():
    """Try to get OAuth access token. Priority:
    1. Widget's own stored credentials
    2. Claude Code's credentials file
    """
    # Check our own stored token
    if CREDENTIALS_FILE.exists():
        try:
            data = json.loads(CREDENTIALS_FILE.read_text())
            token = data.get("accessToken")
            if token:
                return token
        except Exception:
            pass

    # Fall back to Claude Code credentials
    if CLAUDE_CODE_CREDS.exists():
        try:
            data = json.loads(CLAUDE_CODE_CREDS.read_text())
            token = data.get("claudeAiOauth", {}).get("accessToken")
            if token:
                return token
        except Exception:
            pass

    return None


def save_token(token):
    """Save a user-provided OAuth token."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps({
        "accessToken": token,
        "savedAt": datetime.now().isoformat(),
    }))


def clear_token():
    """Remove stored credentials."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()


def is_connected():
    return get_oauth_token() is not None


# ── API ───────────────────────────────────────────────────

def fetch_usage():
    """Fetch usage directly from Anthropic OAuth API."""
    token = get_oauth_token()
    if not token:
        return None

    try:
        req = urllib.request.Request(
            ANTHROPIC_USAGE_API,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": ANTHROPIC_BETA_HEADER,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"error": "auth_expired"}
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

    return {
        "session": _norm(raw.get("five_hour"), "Current session"),
        "weekAll": _norm(raw.get("seven_day"), "Week (all models)"),
        "weekSonnet": _norm(raw.get("seven_day_sonnet"), "Week (Sonnet)"),
        "weekOpus": _norm(raw.get("seven_day_opus"), "Week (Opus)"),
        "extraUsage": _norm_extra(raw.get("extra_usage")),
        "fetchedAt": datetime.now().isoformat(),
    }


def _norm(data, label):
    if not data:
        return None
    return {
        "label": label,
        "utilization": data.get("utilization", 0),
        "resetsAt": data.get("resets_at"),
    }


def _norm_extra(data):
    if not data or not data.get("is_enabled"):
        return None
    return {
        "label": "Extra usage",
        "isEnabled": True,
        "monthlyLimit": data.get("monthly_limit"),
        "usedCredits": data.get("used_credits"),
        "utilization": data.get("utilization", 0),
    }


# ── Helpers ───────────────────────────────────────────────

def time_until(iso_str):
    if not iso_str:
        return "--"
    try:
        reset = datetime.fromisoformat(iso_str)
        now = datetime.now(timezone.utc)
        diff = (reset - now).total_seconds()
        if diff <= 0:
            return "now"
        d, rem = divmod(int(diff), 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        return f"{d}d {h}h {m}m" if d else f"{h}h {m}m"
    except Exception:
        return "--"


def bar_color(pct):
    if pct >= 85:
        return C["red"]
    if pct >= 50:
        return C["amber"]
    return C["terracotta"]


def rounded_rect(cr, x, y, w, h, r):
    r = min(r, h / 2, w / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def draw_cog(cr, cx, cy, radius, color, alpha=1.0):
    cr.save()
    cr.set_source_rgba(*color, alpha)
    teeth = 6
    outer = radius
    inner = radius * 0.55
    tooth_half = math.pi / teeth / 2.2
    cr.new_path()
    for i in range(teeth):
        angle = 2 * math.pi * i / teeth
        cr.line_to(cx + outer * math.cos(angle - tooth_half),
                   cy + outer * math.sin(angle - tooth_half))
        cr.line_to(cx + outer * math.cos(angle + tooth_half),
                   cy + outer * math.sin(angle + tooth_half))
        na = 2 * math.pi * (i + 0.5) / teeth
        cr.line_to(cx + inner * math.cos(na - tooth_half),
                   cy + inner * math.sin(na - tooth_half))
        cr.line_to(cx + inner * math.cos(na + tooth_half),
                   cy + inner * math.sin(na + tooth_half))
    cr.close_path()
    cr.fill()
    cr.set_source_rgba(*C["bg"], alpha)
    cr.arc(cx, cy, radius * 0.25, 0, 2 * math.pi)
    cr.fill()
    cr.restore()


# ── Widget ────────────────────────────────────────────────

class UsageWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_NAME)
        self.settings = load_settings()
        self.alpha = self.settings["opacity"]
        self.data = None
        self.drag_offset = None
        self.cog_hover = False
        self.popover_visible = False
        self.content_h = 250
        self.auth_error = False
        self.timer_id = None

        # Window setup
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_below(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        # Position
        if self.settings["x"] >= 0 and self.settings["y"] >= 0:
            self.move(self.settings["x"], self.settings["y"])
        else:
            display = Gdk.Display.get_default()
            mon = display.get_primary_monitor() or display.get_monitor(0)
            geom = mon.get_geometry()
            self.move(geom.x + geom.width - 320, geom.y + 60)

        # Overlay
        overlay = Gtk.Overlay()
        self.add(overlay)

        # Canvas
        self.canvas = Gtk.DrawingArea()
        self.canvas.set_size_request(WIDGET_W, 250)
        self.canvas.connect("draw", self.on_draw)
        self.canvas.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.canvas.connect("button-press-event", self.on_press)
        self.canvas.connect("button-release-event", self.on_release)
        self.canvas.connect("motion-notify-event", self.on_motion)
        overlay.add(self.canvas)

        # Popover anchor
        self.cog_anchor = Gtk.Label()
        self.cog_anchor.set_halign(Gtk.Align.END)
        self.cog_anchor.set_valign(Gtk.Align.START)
        self.cog_anchor.set_margin_end(10)
        self.cog_anchor.set_margin_top(10)
        self.cog_anchor.set_size_request(1, 1)
        overlay.add_overlay(self.cog_anchor)

        # Build popover
        self._build_popover()

        # CSS
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window { background-color: transparent; }
            popover, popover * {
                background-color: #1c1714;
                color: #E8D5C4;
            }
            popover label { color: #7a6555; }
            popover .connect-label { color: #E8D5C4; }
            scale trough {
                background-color: #3d3529;
                min-height: 4px; border-radius: 2px;
            }
            scale highlight {
                background-color: #D97757;
                min-height: 4px; border-radius: 2px;
            }
            scale slider {
                background-color: #E8D5C4;
                min-width: 14px; min-height: 14px; border-radius: 7px;
            }
            button {
                background-color: #3d3529;
                color: #E8D5C4;
                border: 1px solid #4a3f35;
                border-radius: 4px;
                padding: 4px 12px;
            }
            button:hover {
                background-color: #D97757;
                color: #1c1714;
            }
            button.connect-btn {
                background-color: #D97757;
                color: #1c1714;
                font-weight: bold;
            }
            button.connect-btn:hover {
                background-color: #E8D5C4;
            }
            button.disconnect-btn {
                background-color: transparent;
                color: #7a6555;
                border: 1px solid #4a3f35;
                font-size: 9px;
            }
            button.disconnect-btn:hover {
                color: #ff5545;
                border-color: #ff5545;
            }
            entry {
                background-color: #3d3529;
                color: #E8D5C4;
                border: 1px solid #4a3f35;
                border-radius: 4px;
                padding: 4px 8px;
                caret-color: #D97757;
            }
            entry:focus {
                border-color: #D97757;
            }
            *:link, button:link {
                color: #7a6555;
                background: transparent;
                border: none; padding: 0;
                font-size: 9px;
            }
            *:link:hover, button:link:hover {
                color: #D97757;
                background: transparent;
            }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Start
        self.refresh_data()
        self.timer_id = GLib.timeout_add_seconds(POLL_SECONDS, self.refresh_data)
        self.show_all()

    def _build_popover(self):
        """Build settings popover with connect/disconnect and opacity."""
        self.popover = Gtk.Popover()
        self.popover.set_relative_to(self.cog_anchor)
        self.popover.set_position(Gtk.PositionType.BOTTOM)
        self.popover.connect("closed", lambda _: setattr(self, 'popover_visible', False))

        self.pop_stack = Gtk.Stack()
        self.pop_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        # ── Connected view ──
        connected_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        connected_box.set_margin_start(12)
        connected_box.set_margin_end(12)
        connected_box.set_margin_top(10)
        connected_box.set_margin_bottom(10)

        # Status
        self.status_label = Gtk.Label()
        self.status_label.set_markup(
            '<span foreground="#44bb66" font_desc="9">Connected</span>'
        )
        self.status_label.set_halign(Gtk.Align.START)
        connected_box.pack_start(self.status_label, False, False, 0)

        # Opacity
        lbl = Gtk.Label(label="Opacity")
        lbl.set_halign(Gtk.Align.START)
        connected_box.pack_start(lbl, False, False, 0)

        self.opacity_slider = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.2, 1.0, 0.05
        )
        self.opacity_slider.set_value(self.alpha)
        self.opacity_slider.set_size_request(180, -1)
        self.opacity_slider.set_draw_value(True)
        self.opacity_slider.set_value_pos(Gtk.PositionType.RIGHT)
        self.opacity_slider.connect("value-changed", self.on_opacity_changed)
        connected_box.pack_start(self.opacity_slider, False, False, 0)

        # Disconnect
        disc_btn = Gtk.Button(label="Disconnect Account")
        disc_btn.get_style_context().add_class("disconnect-btn")
        disc_btn.connect("clicked", self.on_disconnect)
        connected_box.pack_start(disc_btn, False, False, 2)

        # Attribution
        attr_btn = Gtk.LinkButton.new_with_label(
            "https://boutabyte.com", "Built by Boutabyte"
        )
        attr_btn.set_halign(Gtk.Align.CENTER)
        connected_box.pack_start(attr_btn, False, False, 4)

        # Quit
        quit_btn = Gtk.Button(label="Quit Widget")
        quit_btn.connect("clicked", lambda _: Gtk.main_quit())
        connected_box.pack_start(quit_btn, False, False, 2)

        self.pop_stack.add_named(connected_box, "connected")

        # ── Not connected view ──
        connect_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        connect_box.set_margin_start(12)
        connect_box.set_margin_end(12)
        connect_box.set_margin_top(10)
        connect_box.set_margin_bottom(10)

        info_label = Gtk.Label()
        info_label.set_markup(
            '<span foreground="#E8D5C4" font_desc="9">Connect your Claude account\n'
            'to view subscription usage.</span>'
        )
        info_label.set_line_wrap(True)
        info_label.set_max_width_chars(28)
        info_label.get_style_context().add_class("connect-label")
        connect_box.pack_start(info_label, False, False, 0)

        # Auto-detect notice
        detect_label = Gtk.Label()
        detect_label.set_markup(
            '<span foreground="#7a6555" font_desc="8">'
            'Auto-detects Claude Code credentials,\n'
            'or paste your OAuth token below.</span>'
        )
        detect_label.set_line_wrap(True)
        detect_label.set_max_width_chars(28)
        connect_box.pack_start(detect_label, False, False, 0)

        # Token entry
        self.token_entry = Gtk.Entry()
        self.token_entry.set_placeholder_text("sk-ant-oat01-...")
        self.token_entry.set_visibility(False)  # password-style
        self.token_entry.set_size_request(200, -1)
        connect_box.pack_start(self.token_entry, False, False, 0)

        # Connect button
        conn_btn = Gtk.Button(label="Connect Account")
        conn_btn.get_style_context().add_class("connect-btn")
        conn_btn.connect("clicked", self.on_connect)
        connect_box.pack_start(conn_btn, False, False, 2)

        self.connect_error_label = Gtk.Label()
        self.connect_error_label.set_markup("")
        self.connect_error_label.set_halign(Gtk.Align.START)
        connect_box.pack_start(self.connect_error_label, False, False, 0)

        # Attribution
        attr_btn2 = Gtk.LinkButton.new_with_label(
            "https://boutabyte.com", "Built by Boutabyte"
        )
        attr_btn2.set_halign(Gtk.Align.CENTER)
        connect_box.pack_start(attr_btn2, False, False, 4)

        # Quit
        quit_btn2 = Gtk.Button(label="Quit Widget")
        quit_btn2.connect("clicked", lambda _: Gtk.main_quit())
        connect_box.pack_start(quit_btn2, False, False, 2)

        self.pop_stack.add_named(connect_box, "connect")
        self.popover.add(self.pop_stack)
        self.popover.show_all()
        self.popover.hide()

        self._update_popover_view()

    def _update_popover_view(self):
        if is_connected():
            self.pop_stack.set_visible_child_name("connected")
            if self.auth_error:
                self.status_label.set_markup(
                    '<span foreground="#ff5545" font_desc="9">Token expired — reconnect</span>'
                )
            else:
                self.status_label.set_markup(
                    '<span foreground="#44bb66" font_desc="9">Connected</span>'
                )
        else:
            self.pop_stack.set_visible_child_name("connect")

    def on_connect(self, btn):
        token = self.token_entry.get_text().strip()
        if not token:
            # Try to auto-detect from Claude Code
            if CLAUDE_CODE_CREDS.exists():
                self.connect_error_label.set_markup(
                    '<span foreground="#44bb66" font_desc="8">'
                    'Found Claude Code credentials!</span>'
                )
                self.auth_error = False
                self._update_popover_view()
                self.refresh_data()
                return
            self.connect_error_label.set_markup(
                '<span foreground="#ff5545" font_desc="8">'
                'Enter a token or install Claude Code</span>'
            )
            return

        # Validate token by hitting the API
        try:
            req = urllib.request.Request(
                ANTHROPIC_USAGE_API,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": ANTHROPIC_BETA_HEADER,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            # Valid — save it
            save_token(token)
            self.auth_error = False
            self.token_entry.set_text("")
            self.connect_error_label.set_markup("")
            self._update_popover_view()
            self.refresh_data()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.connect_error_label.set_markup(
                    '<span foreground="#ff5545" font_desc="8">'
                    'Invalid or expired token</span>'
                )
            else:
                self.connect_error_label.set_markup(
                    f'<span foreground="#ff5545" font_desc="8">'
                    f'API error: {e.code}</span>'
                )
        except Exception as e:
            self.connect_error_label.set_markup(
                f'<span foreground="#ff5545" font_desc="8">'
                f'Connection failed</span>'
            )

    def on_disconnect(self, btn):
        clear_token()
        self.data = None
        self.auth_error = False
        self._update_popover_view()
        self.canvas.queue_draw()

    # ── Cog hit test ──
    def _cog_rect(self):
        return (WIDGET_W - 14 - COG_SIZE, 8, COG_SIZE, COG_SIZE)

    def _in_cog(self, x, y):
        cx, cy, cw, ch = self._cog_rect()
        return cx <= x <= cx + cw and cy <= y <= cy + ch

    # ── Input ──
    def on_press(self, widget, event):
        if event.button == 1:
            if self._in_cog(event.x, event.y):
                self._update_popover_view()
                self.popover_visible = not self.popover_visible
                if self.popover_visible:
                    self.popover.popup()
                else:
                    self.popover.popdown()
                return True
            if event.y <= TITLE_H:
                self.drag_offset = (event.x_root, event.y_root,
                                    *self.get_position())
        return True

    def on_release(self, widget, event):
        if self.drag_offset:
            self.drag_offset = None
            x, y = self.get_position()
            self.settings["x"] = x
            self.settings["y"] = y
            save_settings(self.settings)
        return True

    def on_motion(self, widget, event):
        if self.drag_offset:
            ox, oy, wx, wy = self.drag_offset
            self.move(int(wx + event.x_root - ox),
                      int(wy + event.y_root - oy))
        else:
            was = self.cog_hover
            self.cog_hover = self._in_cog(event.x, event.y)
            if was != self.cog_hover:
                self.canvas.queue_draw()
        return True

    # ── Settings ──
    def on_opacity_changed(self, scale):
        self.alpha = round(scale.get_value(), 2)
        self.settings["opacity"] = self.alpha
        save_settings(self.settings)
        self.canvas.queue_draw()

    # ── Data ──
    def refresh_data(self):
        if not is_connected():
            self.data = None
            self.canvas.queue_draw()
            return True

        result = fetch_usage()
        if result and result.get("error") == "auth_expired":
            self.auth_error = True
            self.data = None
        elif result and "error" not in result:
            self.auth_error = False
            self.data = result
        # On other errors, keep stale data
        self.canvas.queue_draw()
        return True

    # ── Drawing ──
    def on_draw(self, widget, cr):
        a = self.alpha
        alloc = widget.get_allocation()
        w = alloc.width
        h = alloc.height

        # Clear
        cr.set_operator(0)  # CLEAR
        cr.paint()
        cr.set_operator(2)  # OVER

        # Background
        rounded_rect(cr, 0, 0, w, h, 10)
        cr.set_source_rgba(*C["bg"], a)
        cr.fill()

        # Border
        rounded_rect(cr, 0.5, 0.5, w - 1, h - 1, 10)
        cr.set_source_rgba(*C["dim"], a * 0.5)
        cr.set_line_width(1)
        cr.stroke()

        pad = 14
        y = 18

        # Title
        cr.select_font_face("JetBrains Mono", 0, 1)
        cr.set_font_size(13)
        cr.set_source_rgba(*C["terracotta"], a)
        cr.move_to(pad, y)
        cr.show_text("claude")
        tx = cr.get_current_point()[0]
        cr.select_font_face("JetBrains Mono", 0, 0)
        cr.set_source_rgba(*C["cream"], a)
        cr.move_to(tx, y)
        cr.show_text(" usage")

        # Cog
        cog_cx = WIDGET_W - pad - COG_SIZE / 2
        cog_cy = y - 4
        cog_color = C["terracotta"] if self.cog_hover else C["label"]
        draw_cog(cr, cog_cx, cog_cy, 8, cog_color, a)

        # Title divider
        y += 8
        cr.set_source_rgba(*C["dim"], a * 0.6)
        cr.set_line_width(0.5)
        cr.move_to(pad, y)
        cr.line_to(w - pad, y)
        cr.stroke()
        y += 14

        # Not connected state
        if not is_connected() or self.auth_error:
            cr.select_font_face("JetBrains Mono", 0, 0)
            cr.set_font_size(10)

            if self.auth_error:
                cr.set_source_rgba(*C["red"], a)
                cr.move_to(pad, y + 12)
                cr.show_text("Token expired")
                y += 28
                cr.set_source_rgba(*C["label"], a)
                cr.set_font_size(9)
                cr.move_to(pad, y)
                cr.show_text("Click the cog to reconnect")
            else:
                cr.set_source_rgba(*C["label"], a)
                cr.move_to(pad, y + 12)
                cr.show_text("No account connected")
                y += 28
                cr.set_source_rgba(*C["dim"], a)
                cr.set_font_size(9)
                cr.move_to(pad, y)
                cr.show_text("Click the cog to connect")

            needed_h = y + 20
            if needed_h != self.content_h:
                self.content_h = needed_h
                self.canvas.set_size_request(WIDGET_W, needed_h)
            return

        if not self.data:
            cr.select_font_face("JetBrains Mono", 0, 0)
            cr.set_font_size(10)
            cr.set_source_rgba(*C["label"], a)
            cr.move_to(pad, y + 12)
            cr.show_text("Loading...")
            return

        # Meters
        bar_w = w - pad * 2 - 50
        bar_h = 6
        bar_r = 3

        meters = [
            ("Session", self.data.get("session"), True),
            ("Week \u00b7 All", self.data.get("weekAll"), False),
            ("Week \u00b7 Sonnet", self.data.get("weekSonnet"), False),
            ("Week \u00b7 Opus", self.data.get("weekOpus"), False),
        ]

        for label, meter, show_session_reset in meters:
            # Skip meters that don't exist on this plan
            if meter is None or meter.get("utilization") is None:
                continue

            cr.select_font_face("JetBrains Mono", 0, 0)
            cr.set_font_size(9)
            cr.set_source_rgba(*C["label"], a)
            cr.move_to(pad, y)
            cr.show_text(label)

            if show_session_reset:
                resets = time_until(meter.get("resetsAt"))
                txt = f"resets {resets}"
                ext = cr.text_extents(txt)
                cr.set_source_rgba(*C["dim"], a)
                cr.move_to(w - pad - ext.width, y)
                cr.show_text(txt)

            y += 10

            pct = meter["utilization"]
            clamped = max(0.0, min(100.0, pct))
            fill_w = max(0, int(bar_w * clamped / 100.0))
            fc = bar_color(clamped)

            rounded_rect(cr, pad, y, bar_w, bar_h, bar_r)
            cr.set_source_rgba(*C["bar_empty"], a)
            cr.fill()

            if fill_w > 1:
                rounded_rect(cr, pad, y, fill_w, bar_h, bar_r)
                cr.set_source_rgba(*fc, a)
                cr.fill()

            cr.set_font_size(10)
            cr.set_source_rgba(*fc, a)
            cr.move_to(pad + bar_w + 8, y + bar_h)
            cr.show_text(f"{pct:.0f}%")

            y += bar_h + 16

        # Bottom divider
        y += 2
        cr.set_source_rgba(*C["dim"], a * 0.6)
        cr.set_line_width(0.5)
        cr.move_to(pad, y)
        cr.line_to(w - pad, y)
        cr.stroke()

        # Weekly reset
        y += 16
        week_resets = time_until(
            (self.data.get("weekAll") or {}).get("resetsAt")
        )
        cr.set_font_size(9)
        cr.set_source_rgba(*C["label"], a)
        cr.move_to(pad, y)
        cr.show_text("Weekly reset")
        cr.set_source_rgba(*C["terracotta"], a)
        cr.move_to(pad + 100, y)
        cr.show_text(week_resets)

        needed_h = y + 16
        if needed_h != self.content_h:
            self.content_h = needed_h
            self.canvas.set_size_request(WIDGET_W, needed_h)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    w = UsageWidget()
    w.connect("destroy", Gtk.main_quit)
    Gtk.main()
