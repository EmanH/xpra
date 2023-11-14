#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2015-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.os_util import WIN32, first_time, gi_import

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")


def add_close_accel(window, callback: Callable) -> list[Gtk.AccelGroup]:
    accel_groups = []

    def wa(s, cb):
        accel_groups.append(add_window_accel(window, s, cb))
    wa('<control>F4', callback)
    wa('<Alt>F4', callback)
    wa('Escape', callback)
    return accel_groups


def add_window_accel(window, accel, callback: Callable) -> Gtk.AccelGroup:
    def connect(ag, *args):
        ag.connect(*args)
    accel_group = Gtk.AccelGroup()
    key, mod = Gtk.accelerator_parse(accel)
    connect(accel_group, key, mod, Gtk.AccelFlags.LOCKED, callback)
    window.add_accel_group(accel_group)
    return accel_group


def GDKWindow(*args, **kwargs) -> Gdk.Window:
    return new_GDKWindow(Gdk.Window, *args, **kwargs)


def new_GDKWindow(gdk_window_class,
                  parent=None, width=1, height=1, window_type=None,
                  event_mask=0, wclass=None, title=None,
                  x=None, y=None, override_redirect=False, visual=None) -> Gdk.Window:
    if window_type is None:
        window_type = Gdk.WindowType.TOPLEVEL
    if wclass is None:
        wclass = Gdk.WindowWindowClass.INPUT_OUTPUT
    attributes_mask = 0
    attributes = Gdk.WindowAttr()
    if x is not None:
        attributes.x = x
        attributes_mask |= Gdk.WindowAttributesType.X
    if y is not None:
        attributes.y = y
        attributes_mask |= Gdk.WindowAttributesType.Y
    # attributes.type_hint = Gdk.WindowTypeHint.NORMAL
    # attributes_mask |= Gdk.WindowAttributesType.TYPE_HINT
    attributes.width = width
    attributes.height = height
    attributes.window_type = window_type
    if title:
        attributes.title = title
        attributes_mask |= Gdk.WindowAttributesType.TITLE
    if visual:
        attributes.visual = visual
        attributes_mask |= Gdk.WindowAttributesType.VISUAL
    # OR:
    attributes.override_redirect = override_redirect
    attributes_mask |= Gdk.WindowAttributesType.NOREDIR
    # events:
    attributes.event_mask = event_mask
    # wclass:
    attributes.wclass = wclass
    mask = Gdk.WindowAttributesType(attributes_mask)
    return gdk_window_class(parent, attributes, mask)


def set_visual(window, alpha=True) -> Gdk.Visual | None:
    screen = window.get_screen()
    if alpha:
        visual = screen.get_rgba_visual()
    else:
        visual = screen.get_system_visual()
    from xpra.log import Logger
    alphalog = Logger("gtk", "alpha")
    alphalog("set_visual(%s, %s) screen=%s, visual=%s", window, alpha, screen, visual)
    # we can't do alpha on win32 with plain GTK,
    # (though we handle it in the opengl backend)
    l : Callable = alphalog.warn
    if WIN32 or not first_time("no-rgba"):
        l = alphalog.debug
    if alpha and visual is None or (not WIN32 and not screen.is_composited()):
        l("Warning: cannot handle window transparency")
        if visual is None:
            l(" no RGBA visual")
        else:
            assert not screen.is_composited()
            l(" screen is not composited")
        return None
    alphalog("set_visual(%s, %s) using visual %s", window, alpha, visual)
    if visual:
        window.set_visual(visual)
    return visual
